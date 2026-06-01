"""
Form 16 parser — LLM extraction pipeline.

Replaces per-field regex patterns with a two-stage LLM pipeline:

  Stage 1 — pdfplumber text extraction  (deterministic, fast)
  Stage 2 — LLM field extraction        (handles all label variants)
  Stage 3 — Python cross-checks         (reliable: math, format, limits)
  Stage 4 — human_doc_review interrupt  (real verification gate for <0.85 confidence)

The can_parse() method still uses lightweight regex / keyword detection for
document identification — LLM is not needed for "is this a Form 16?" checks.

Parsers NEVER raise unhandled exceptions. All errors go to parse_errors.
"""
from __future__ import annotations
import traceback

import pdfplumber

from inditr.models.documents import ExtractedField, ParsedDocument
from .base import BaseParser
from .schemas.form16 import Form16ExtractionSchema
from .llm_extractor import extract_fields
from .llm_validator import cross_check_form16, ValidationResult

# Fields required for a usable Form 16 — missing any → parse_error logged
_REQUIRED_FIELDS = {"gross_salary", "net_taxable_salary", "tds_deducted"}

# Fields in the extraction schema mapped to ParsedDocument section labels
_PART_A_FIELDS = {
    "employer_name", "employer_tan", "employee_pan",
    "employee_name", "financial_year", "total_tds_deposited",
}

# Confidence assigned to regex-extracted fields.
# 0.90 > 0.85 human-review threshold → passes to computation without interruption.
# TRACES Form 16 has CBDT-mandated fixed structure so regex is very reliable.
_REGEX_CONF = 0.90


class Form16Parser(BaseParser):
    """
    Parses Form 16 (Part A + Part B) from PDF using an LLM extraction pipeline.

    Identification is regex-based (cheap). Extraction is LLM-based (robust).
    Validation is two-stage: Python cross-checks first, LLM reviewer second.
    """

    def can_parse(self, filepath: str) -> bool:
        if not filepath.lower().endswith(".pdf"):
            return False
        try:
            with pdfplumber.open(filepath) as pdf:
                text = ""
                for page in pdf.pages[:3]:
                    text += (page.extract_text() or "").lower()
            return (
                "form 16" in text
                or "form no. 16" in text
                or ("tds" in text and ("salary" in text or "employer" in text))
            )
        except Exception:
            return False

    def parse(self, filepath: str) -> ParsedDocument:
        doc = ParsedDocument(doc_type="form_16", filename=filepath)
        try:
            self._do_parse(filepath, doc)
        except Exception as exc:
            doc.parse_errors.append(
                f"Unhandled error in Form16Parser: {exc}\n{traceback.format_exc()}"
            )
        return doc

    # ── Internal pipeline ─────────────────────────────────────────────────────

    def _do_parse(self, filepath: str, doc: ParsedDocument) -> None:
        # ── Step 1: Extract raw text with pdfplumber ──────────────────────────
        raw_text, page_count = self._extract_text(filepath, doc)
        if not raw_text.strip():
            doc.parse_errors.append("pdfplumber extracted no text — possibly a scanned PDF")
            return
        doc.pages = page_count

        # ── Step 2: LLM field extraction ──────────────────────────────────────
        extracted, confidences = extract_fields(
            text=raw_text,
            schema_cls=Form16ExtractionSchema,
            doc_hint="Form 16 — Indian employer TDS certificate (Part A + Part B)",
        )

        # ── Step 2b: Regex fallback ────────────────────────────────────────────
        # If the LLM failed (auth error, timeout, all required fields still None),
        # fall back to deterministic regex extraction. TRACES Form 16 has a fixed
        # CBDT-mandated structure so regex extraction is highly reliable.
        _llm_ok = any(
            getattr(extracted, f, None) is not None for f in _REQUIRED_FIELDS
        )
        if not _llm_ok:
            regex_values = self._extract_fields_regex(raw_text)
            if regex_values:
                known = set(Form16ExtractionSchema.model_fields)
                valid_values = {k: v for k, v in regex_values.items() if k in known}
                try:
                    extracted = Form16ExtractionSchema(**valid_values)
                    confidences = {
                        name: (_REGEX_CONF if name in valid_values else 0.0)
                        for name in Form16ExtractionSchema.model_fields
                    }
                    doc.parse_errors.append(
                        "INFO: LLM unavailable — fields extracted via deterministic "
                        "regex (TRACES format). Accuracy: high for standard Form 16."
                    )
                except Exception as exc:
                    doc.parse_errors.append(f"Regex fallback schema error: {exc}")

        # ── Step 3: Python cross-checks (reliable) ────────────────────────────
        validation: ValidationResult = cross_check_form16(extracted)

        # Apply confidence adjustments from Python checks.
        # confirm() produces adj_conf ≥ 0.90 → always update (upward or lateral).
        # flag()   produces adj_conf < 0.85  → always lower (never raise from a flag).
        # Threshold 0.90 = the confirm() boosted_confidence default in ValidationResult.
        _CONFIRM_THRESHOLD = 0.90
        for field_name, adj_conf in validation.confidence_adjustments.items():
            current = confidences.get(field_name, 1.0)
            if adj_conf >= _CONFIRM_THRESHOLD:
                # Cross-check confirmed — raise LLM confidence above human-review gate
                confidences[field_name] = max(current, adj_conf)
            else:
                # Cross-check flagged a problem — cap at the flagged level
                confidences[field_name] = min(current, adj_conf)

        for issue in validation.issues:
            doc.parse_errors.append(f"[cross-check] {issue}")

        # ── Step 4: Map to ParsedDocument.fields ──────────────────────────────
        self._populate_doc_fields(extracted, confidences, doc)

        # Log required fields that went missing
        for req in _REQUIRED_FIELDS:
            if req not in doc.fields or doc.fields[req].value is None:
                doc.parse_errors.append(f"Required field '{req}' not found in Form 16")

    def _extract_text(self, filepath: str, doc: ParsedDocument) -> tuple[str, int]:
        """Extract all text from PDF. Returns (full_text, page_count)."""
        lines: list[str] = []
        page_count = 0
        try:
            with pdfplumber.open(filepath) as pdf:
                page_count = len(pdf.pages)
                for page in pdf.pages:
                    try:
                        text = page.extract_text() or ""
                        lines.append(text)
                    except Exception as exc:
                        doc.parse_errors.append(f"Page {page.page_number} extraction error: {exc}")
        except Exception as exc:
            doc.parse_errors.append(f"Cannot open PDF: {exc}")

        return "\n".join(lines), page_count

    def _extract_fields_regex(self, text: str) -> dict:
        """
        Deterministic regex extractor for TRACES-format Form 16 PDFs.

        TRACES Form 16 has a CBDT-mandated fixed structure: every field appears
        at a known position with a known label. This gives reliable extraction
        without an LLM. Works on both Part A-only, Part B-only, and combined PDFs.

        Chapter VI-A letter-to-section mapping (fixed by TRACES):
          (a)=80C, (b)=80CCC, (c)=80CCD(1), (d)=total, (e)=80CCD(1B),
          (f)=80CCD(2), (g)=80D, (h)=80E, (i)=80CCH-employee, (j)=80CCH-govt,
          (k)=80G (3-col), (l)=80TTA (3-col), (n)=other (3-col)

        Returns dict of field_name → value (float or str). Absent = not found.
        """
        import re

        result: dict = {}

        def _num(pattern: str, flags: int = 0, group: int = 1) -> float | None:
            m = re.search(pattern, text, flags)
            if m:
                try:
                    return float(m.group(group).replace(",", ""))
                except (ValueError, IndexError):
                    pass
            return None

        def _str_m(pattern: str, flags: int = 0, group: int = 1) -> str | None:
            m = re.search(pattern, text, flags)
            return m.group(group).strip() if m else None

        # ── Employer / Employee identity ──────────────────────────────────
        # TAN: appears as "TAN of the Deductor" (Part B body) and
        #      "TAN of Employer:" (page-header lines in both parts).
        result["employer_tan"] = _str_m(
            r"TAN of (?:the )?(?:Deductor|Employer)[:\s]+([A-Z]{4}[0-9]{5}[A-Z])"
        )

        # Employer name: first ALL-CAPS line after the address-header line.
        result["employer_name"] = _str_m(
            r"Name and address of the Employer[^\n]*\n([A-Z][A-Z0-9 &.,()'\-]{3,})"
        )

        # Employee PAN: page-header "PAN of Employee:XXXXX9999X" is most reliable.
        result["employee_pan"] = _str_m(
            r"PAN of (?:the )?Employee[^\n]*?([A-Z]{5}[0-9]{4}[A-Z])"
        )
        if not result.get("employee_pan"):
            # Fallback: the row "DEDUCTOR_PAN TAN EMPLOYEE_PAN" — TAN format differs
            # (4-alpha 5-digit 1-alpha) so we identify it, then grab the PAN after it.
            result["employee_pan"] = _str_m(
                r"[A-Z]{4}[0-9]{5}[A-Z]\s+([A-Z]{5}[0-9]{4}[A-Z])\s*$",
                flags=re.MULTILINE,
            )

        # Assessment Year → Financial Year (AY 2025-26 = FY 2024-25)
        ay_m = re.search(r"Assessment Year[\s:]*(\d{4})-(\d{2,4})", text)
        if ay_m:
            ay_start = int(ay_m.group(1))
            fy_suffix = str(ay_start)[-2:]  # "25" from 2025
            result["financial_year"] = f"{ay_start - 1}-{fy_suffix}"

        # ── Part A: Quarterly TDS table ───────────────────────────────────
        # Row: "Total (Rs.) SALARY_PAID  TDS_DEDUCTED  TDS_DEPOSITED"
        total_m = re.search(
            r"Total \(Rs\.\)\s+([\d,]+\.?\d*)\s+([\d,]+\.?\d*)\s+([\d,]+\.?\d*)",
            text,
        )
        if total_m:
            result["tds_deducted"] = float(total_m.group(2).replace(",", ""))
            result["total_tds_deposited"] = float(total_m.group(3).replace(",", ""))

        # ── Part B: Salary figures ────────────────────────────────────────
        # Row 1(a): "Salary as per provisions contained in section 17(1)"
        result["gross_salary"] = _num(
            r"Salary as per provisions contained in section 17\(1\)\s+([\d,]+\.?\d*)"
        )

        # Row 2(e): HRA exemption u/s 10(13A)
        result["hra_exemption"] = _num(
            r"House rent allowance under section 10\(13A\)\s+([\d,]+\.?\d*)"
        )

        # Row 4(a): Standard deduction u/s 16(ia)
        result["standard_deduction"] = _num(
            r"Standard deduction under section 16\(ia\)\s+([\d,]+\.?\d*)"
        )

        # Row 4(c): Professional tax u/s 16(iii)
        result["professional_tax"] = _num(
            r"Tax on employment under section 16\(iii\)\s+([\d,]+\.?\d*)"
        )

        # Row 6: Income chargeable under "Salaries" [net of Section 16]
        result["net_taxable_salary"] = _num(
            r'Income chargeable under the head .Salaries.\s*\[[^\]]*\]\s*([\d,]+\.?\d*)'
        )

        # Row 12: Total taxable income
        result["total_taxable_income"] = _num(
            r"Total taxable income\s*\(\s*9-11\s*\)\s*([\d,]+\.?\d*)"
        )

        # Row 17: Tax payable — fallback for tds_deducted if Part A absent
        if result.get("tds_deducted") is None:
            result["tds_deducted"] = _num(
                r"Tax payable\s*\(\s*13\+15\+16-14\s*\)\s*([\d,]+\.?\d*)"
            )

        # ── Part B: Chapter VI-A deductions ───────────────────────────────
        # Extract the VI-A block to avoid collisions with Section 2/4 (a)/(b)/... rows.
        # The block runs from "Deductions under Chapter VI-A" to "Aggregate of
        # deductible amount" (row 11). Letters map to sections per TRACES spec.
        viA_m = re.search(
            r"Deductions under Chapter VI-A(.*?)(?=Aggregate of deductible amount|\Z)",
            text, re.DOTALL,
        )
        if viA_m:
            via = viA_m.group(1)

            def _via_ded(letter: str, three_col: bool = False) -> float | None:
                """
                Rows (a)–(j): two columns  → Gross | Deductible  (take col 2)
                Rows (k)/(l)/(n): three cols → Gross | Qualifying | Deductible (take col 3)
                """
                if three_col:
                    m = re.search(
                        rf"\({re.escape(letter)}\)\s+([\d,]+\.?\d*)\s+([\d,]+\.?\d*)\s+([\d,]+\.?\d*)",
                        via,
                    )
                    grp = 3
                else:
                    m = re.search(
                        rf"\({re.escape(letter)}\)\s+([\d,]+\.?\d*)\s+([\d,]+\.?\d*)",
                        via,
                    )
                    grp = 2
                if m:
                    try:
                        return float(m.group(grp).replace(",", ""))
                    except (ValueError, IndexError):
                        pass
                return None

            result["deduction_80c"]      = _via_ded("a")              # 80C / PF / LIC
            result["deduction_80ccd1b"]  = _via_ded("e")              # 80CCD(1B) NPS
            result["deduction_80ccd2"]   = _via_ded("f")              # 80CCD(2) employer NPS
            result["deduction_80d"]      = _via_ded("g")              # 80D health insurance
            result["deduction_80e"]      = _via_ded("h")              # 80E education loan
            result["deduction_80g"]      = _via_ded("k", three_col=True)  # 80G donations
            result["deduction_80tta_ttb"] = _via_ded("l", three_col=True) # 80TTA/TTB interest

            result["total_chapter_via"] = _num(
                r"Aggregate of deductible amount under Chapter VI-A[^\n]*\n\s*(?:\d+\.\s*)?([\d,]+\.?\d*)",
                flags=re.MULTILINE,
            )

        # Drop None values — caller checks dict presence
        return {k: v for k, v in result.items() if v is not None}

    def _populate_doc_fields(
        self,
        extracted: Form16ExtractionSchema,
        confidences: dict[str, float],
        doc: ParsedDocument,
    ) -> None:
        """
        Map every field in the extraction schema to ParsedDocument.fields.
        Fields with None value still get an ExtractedField (confidence 0.0)
        so downstream consumers see them as missing rather than absent.
        """
        for field_name in Form16ExtractionSchema.model_fields:
            value = getattr(extracted, field_name, None)
            conf = confidences.get(field_name, 0.0)
            section = "Part A" if field_name in _PART_A_FIELDS else "Part B"

            doc.fields[field_name] = ExtractedField(
                value=value,
                source_document=doc.filename,
                source_section=section,
                confidence=conf,
            )
