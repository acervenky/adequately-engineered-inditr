"""
Salary slip parser — extracts basic salary, HRA, allowances, deductions, net pay.
Supports common Indian payslip formats via keyword heuristics.
Parsers NEVER raise unhandled exceptions.
"""
from __future__ import annotations
import re
import traceback
from typing import Optional

import pdfplumber

from inditr.models.documents import ExtractedField, ParsedDocument
from .base import BaseParser

_EXACT_CONF = 0.95
_FUZZY_CONF = 0.75

_SALARY_PATTERNS = [
    ("basic_salary", [r"basic\s+salary", r"basic\s+pay"], [r"basic"]),
    ("hra", [r"house\s+rent\s+allowance", r"\bhra\b"], [r"h\.r\.a", r"rent\s+allowance"]),
    ("gross_salary", [r"gross\s+salary", r"gross\s+earnings", r"total\s+earnings"], [r"gross\s+pay", r"total\s+gross"]),
    ("net_pay", [r"net\s+pay", r"net\s+salary", r"net\s+take\s+home"], [r"take\s+home", r"net\s+amount"]),
    ("pf_deduction", [r"provident\s+fund", r"\bpf\b", r"epf"], [r"p\.f\."]),
    ("professional_tax", [r"professional\s+tax", r"prof\.\s*tax", r"pt\b"], [r"p\.tax"]),
    ("lta", [r"leave\s+travel\s+allowance", r"\blta\b"], [r"travel\s+allowance"]),
]

_MONTH_RE = re.compile(
    r"(january|february|march|april|may|june|july|august|september|october|november|december"
    r"|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s*[,\-]?\s*(20\d\d)",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(r"[\d,]+\.?\d*")


def _extract_amount(text: str) -> Optional[float]:
    text = text.replace(",", "")
    m = re.search(r"[\d]+\.?\d*", text)
    if m:
        try:
            return float(m.group())
        except ValueError:
            pass
    return None


def _search_lines(lines: list[str], exact_pats: list[str], fuzzy_pats: list[str]) -> tuple[Optional[str], float]:
    for pat in exact_pats:
        for line in lines:
            if re.search(pat, line, re.IGNORECASE):
                return line, _EXACT_CONF
    for pat in fuzzy_pats:
        for line in lines:
            if re.search(pat, line, re.IGNORECASE):
                return line, _FUZZY_CONF
    return None, 0.0


class SalarySlipParser(BaseParser):

    def can_parse(self, filepath: str) -> bool:
        if not filepath.lower().endswith(".pdf"):
            return False
        try:
            with pdfplumber.open(filepath) as pdf:
                text = ""
                for page in pdf.pages[:2]:
                    text += (page.extract_text() or "").lower()
            return (
                ("pay slip" in text or "payslip" in text or "salary slip" in text or "pay stub" in text)
                and ("basic" in text or "gross" in text)
            )
        except Exception:
            return False

    def parse(self, filepath: str) -> ParsedDocument:
        doc = ParsedDocument(doc_type="salary_slip", filename=filepath)
        try:
            self._do_parse(filepath, doc)
        except Exception as exc:
            doc.parse_errors.append(f"Unhandled error in SalarySlipParser: {exc}\n{traceback.format_exc()}")
        return doc

    def _do_parse(self, filepath: str, doc: ParsedDocument) -> None:
        try:
            pdf = pdfplumber.open(filepath)
        except Exception as exc:
            doc.parse_errors.append(f"Cannot open PDF: {exc}")
            return

        with pdf:
            all_lines: list[str] = []
            for page in pdf.pages:
                try:
                    text = page.extract_text() or ""
                    all_lines.extend(text.splitlines())
                except Exception as exc:
                    doc.parse_errors.append(f"Page extraction error: {exc}")

        full_text = " ".join(all_lines)

        # Extract month/year
        m = _MONTH_RE.search(full_text)
        if m:
            doc.fields["pay_period"] = ExtractedField(
                value=f"{m.group(1)} {m.group(2)}",
                source_document=doc.filename,
                source_section="header",
                confidence=_EXACT_CONF,
            )

        # Extract salary components
        for field_name, exact_pats, fuzzy_pats in _SALARY_PATTERNS:
            matched_line, conf = _search_lines(all_lines, exact_pats, fuzzy_pats)
            if matched_line:
                amount = _extract_amount(matched_line)
                doc.fields[field_name] = ExtractedField(
                    value=amount,
                    source_document=doc.filename,
                    source_section="earnings_deductions",
                    confidence=conf,
                    raw_text=matched_line.strip(),
                )
            else:
                if field_name in ("gross_salary", "net_pay"):
                    doc.parse_errors.append(f"Required field '{field_name}' not found in salary slip")
