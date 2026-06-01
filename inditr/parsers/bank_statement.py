"""
Bank statement parser — targeted LLM extraction.

Architecture (2 LLM calls, not N):
  Stage 1 — pdfplumber full text extraction      (deterministic, free)
  Stage 2 — LLM on page-1 sample                 (identify employer + FD/broker patterns)
  Stage 3 — Python grep on full text              (find matching line blocks only)
  Stage 4 — LLM on matched snippets only          (extract date + amount)
  Stage 5 — Pydantic validation                   (type-safe before engine)

Sending the entire statement to the LLM is wasteful and slow — the tax-relevant
credits (salary, FD interest, broker payouts) are a tiny fraction of all lines.
We let Python do the cheap filtering and the LLM do the understanding.
Parsers NEVER raise unhandled exceptions. All errors go to parse_errors.
"""
from __future__ import annotations
import re
import traceback
from typing import Optional

import pdfplumber

from inditr.models.documents import ExtractedField, ParsedDocument
from .base import BaseParser

# ---------------------------------------------------------------------------
# Document identification (no LLM)
# ---------------------------------------------------------------------------
_ID_KEYWORDS = [
    "account statement", "bank statement", "statement of account",
    "statement for a/c", "passbook", "account passbook",
    "transaction history", "account transactions",
    "deposits", "withdrawals",
]

_BANK_NAME_RE = re.compile(
    r"canara\s*bank|hdfc\s*bank|state\s*bank\s*of\s*india|\bsbi\b|icici\s*bank"
    r"|axis\s*bank|kotak\s*(mahindra\s*)?bank|punjab\s*national\s*bank|\bpnb\b"
    r"|bank\s*of\s*baroda|bank\s*of\s*india|idfc\s*first\s*bank|yes\s*bank"
    r"|indusind\s*bank|union\s*bank|central\s*bank|indian\s*bank|uco\s*bank"
    r"|federal\s*bank|karnataka\s*bank|south\s*indian\s*bank|rbl\s*bank"
    r"|bandhan\s*bank|au\s*small\s*finance|equitas\s*small",
    re.IGNORECASE,
)

# Known broker names for payout detection
_BROKER_RE = re.compile(
    r"zerodha|upstox|angel\s*one|groww|hdfc\s*securities|icicidirect"
    r"|kotak\s*securities|motilal|sharekhan|5paisa|fyers|samco|dhan",
    re.IGNORECASE,
)

# Known FD/savings interest keywords
_INTEREST_RE = re.compile(
    r"fd\s*int|fixed\s*deposit\s*int|interest\s*on\s*fd|tdr\s*int|stdr\s*int"
    r"|sbint|sb\s*int|savings\s*bank\s*int|int(?:erest)?\s*for\s*the\s*period",
    re.IGNORECASE,
)

# Context window around each matched transaction block
_CONTEXT_LINES = 8      # lines before and after the matching line
_SAMPLE_CHARS  = 4_000  # first-page sample sent for employer identification
_CONF_FOUND    = 0.80
_CONF_MISS     = 0.0


class BankStatementParser(BaseParser):

    def can_parse(self, filepath: str) -> bool:
        if not filepath.lower().endswith(".pdf"):
            return False
        try:
            with pdfplumber.open(filepath) as pdf:
                text = ""
                for page in pdf.pages[:2]:
                    text += (page.extract_text() or "").lower()
            return bool(_BANK_NAME_RE.search(text)) or any(k in text for k in _ID_KEYWORDS)
        except Exception:
            return False

    def parse(self, filepath: str) -> ParsedDocument:
        doc = ParsedDocument(doc_type="bank_statement", filename=filepath)
        try:
            self._do_parse(filepath, doc)
        except Exception as exc:
            doc.parse_errors.append(
                f"Unhandled error in BankStatementParser: {exc}\n{traceback.format_exc()}"
            )
        return doc

    # ── Pipeline ───────────────────────────────────────────────────────────────

    def _do_parse(self, filepath: str, doc: ParsedDocument) -> None:
        # Stage 1: extract all text (cheap)
        full_text, _ = self._extract_text(filepath, doc)
        if not full_text.strip():
            doc.parse_errors.append("No text extracted — may be a scanned/image PDF")
            return

        all_lines = full_text.splitlines()
        sample = full_text[:_SAMPLE_CHARS]

        # Stage 2: identify what to look for — one LLM call on NEFT credit lines
        # Grep NEFT/IMPS credit lines from the full text (cheap Python), then ask
        # the LLM to identify the employer from those lines rather than hoping
        # the employer appears in the first page.
        neft_lines = self._grep_neft_credits(all_lines)
        patterns = self._identify_patterns(sample, neft_lines, doc)

        # Store metadata discovered in stage 2
        doc.fields["bank_name"] = ExtractedField(
            value=patterns.get("bank_name", "unknown"),
            source_document=doc.filename, source_section="header",
            confidence=_CONF_FOUND if patterns.get("bank_name") else _CONF_MISS,
        )
        doc.fields["account_holder_name"] = ExtractedField(
            value=patterns.get("account_holder_name"),
            source_document=doc.filename, source_section="header",
            confidence=_CONF_FOUND if patterns.get("account_holder_name") else _CONF_MISS,
        )
        doc.fields["period_from"] = ExtractedField(
            value=patterns.get("period_from"),
            source_document=doc.filename, source_section="header",
            confidence=_CONF_FOUND if patterns.get("period_from") else _CONF_MISS,
        )
        doc.fields["period_to"] = ExtractedField(
            value=patterns.get("period_to"),
            source_document=doc.filename, source_section="header",
            confidence=_CONF_FOUND if patterns.get("period_to") else _CONF_MISS,
        )

        # Stage 3: Python grep — collect matching line blocks
        employer_keyword = patterns.get("employer_keyword", "")
        salary_blocks    = self._grep_blocks(all_lines, employer_keyword) if employer_keyword else []
        broker_blocks    = self._grep_blocks(all_lines, _BROKER_RE)
        interest_blocks  = self._grep_blocks(all_lines, _INTEREST_RE)

        # Stage 4: LLM extracts (date, amount) from the small matched snippets,
        # then Python filters to keep only entries whose description matches the
        # expected pattern (employer name, broker name, interest keyword).
        employer_re = (
            re.compile(re.escape(employer_keyword), re.IGNORECASE) if employer_keyword else None
        )
        raw_salary    = self._extract_credits(salary_blocks,  "salary credit",  doc) if salary_blocks else []
        salary_credits = [
            e for e in raw_salary
            if employer_re and employer_re.search(e.get("line", ""))
        ]
        broker_payouts  = self._extract_credits(broker_blocks,  "broker payout",  doc) if broker_blocks else []
        interest_items  = self._extract_credits(interest_blocks,"interest credit", doc) if interest_blocks else []
        fd_interest_total = sum(e["amount"] for e in interest_items)

        # Store fields
        doc.fields["salary_credits"] = ExtractedField(
            value=salary_credits, source_document=doc.filename,
            source_section="transactions",
            confidence=_CONF_FOUND if salary_credits else _CONF_MISS,
        )
        doc.fields["broker_payouts"] = ExtractedField(
            value=broker_payouts, source_document=doc.filename,
            source_section="transactions",
            confidence=_CONF_FOUND if broker_payouts else _CONF_MISS,
        )
        doc.fields["fd_interest_total"] = ExtractedField(
            value=fd_interest_total, source_document=doc.filename,
            source_section="transactions",
            confidence=_CONF_FOUND if fd_interest_total > 0 else _CONF_MISS,
        )

        if not salary_credits:
            doc.parse_errors.append(
                f"No salary credits found"
                + (f" matching '{employer_keyword}'" if employer_keyword else
                   " — employer not identified; enter gross salary manually.")
            )

    # ── Stage 2: identify patterns from first-page sample ─────────────────────

    def _grep_neft_credits(self, lines: list[str]) -> str:
        """
        Collect NEFT/IMPS credit blocks from the full text.
        The company name is typically on lines 1-2 AFTER the 'NEFT CR-...' header line,
        so we grab each hit plus the next 3 lines to give the LLM the full entry.
        Returns a compact listing capped at ~3K chars.
        """
        _NEFT_CR = re.compile(r"NEFT\s*CR|IMPS\s*CR|NEFT-CR|IMPS-CR", re.IGNORECASE)
        blocks: list[str] = []
        for i, line in enumerate(lines):
            if _NEFT_CR.search(line):
                block = lines[i: i + 4]  # hit line + next 3 (company name, amount)
                blocks.append(" | ".join(l.strip() for l in block if l.strip()))
            if len(blocks) >= 30:
                break
        return "\n".join(blocks)

    def _identify_patterns(self, sample: str, neft_lines: str, doc: ParsedDocument) -> dict:
        """
        One LLM call on the first-page sample.
        Returns dict with: bank_name, account_holder_name, period_from, period_to,
        employer_keyword (a short string we can grep for in NEFT credit lines).
        """
        import litellm, json, re as _re
        from inditr.graph.llm import MODEL

        neft_block = f"\n\nNEFT credit lines found across the full statement:\n---\n{neft_lines}\n---" if neft_lines else ""

        prompt = f"""You are analysing an Indian bank e-statement.

From the header sample and NEFT credit lines below, extract:
1. bank_name: the bank's name (e.g. "Canara Bank")
2. account_holder_name: the account holder's full name
3. period_from: statement start date (DD-MM-YYYY)
4. period_to: statement end date (DD-MM-YYYY)
5. employer_keyword: the shortest unique word or phrase from the employer/company name
   visible in the NEFT credit lines that appears REPEATEDLY (salary is monthly).
   Return just the distinctive fragment (e.g. "ACMECORP", not the full NEFT reference).
   Return null if no recurring employer credits are identifiable.

Return ONLY a JSON object, no explanation.

Statement header:
---
{sample}
---{neft_block}

JSON:"""

        try:
            resp = litellm.completion(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=256,
            )
            raw = resp.choices[0].message.content or ""
            cleaned = _re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
            match = _re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                return json.loads(match.group())
        except Exception as exc:
            doc.parse_errors.append(f"Pattern identification LLM call failed: {exc}")

        return {}

    # ── Stage 3: Python grep → matched line blocks ─────────────────────────────

    def _grep_blocks(
        self,
        lines: list[str],
        pattern: "str | re.Pattern",
    ) -> list[str]:
        """
        Find all line indices matching pattern, deduplicate nearby matches,
        and return context windows (CONTEXT_LINES before + after) as text blocks.
        """
        if not pattern:
            return []

        match_fn = (
            (lambda l: bool(pattern.search(l)))
            if hasattr(pattern, "search")
            else (lambda l: pattern.lower() in l.lower())
        )

        # Find matching line indices
        hits = [i for i, line in enumerate(lines) if match_fn(line)]
        if not hits:
            return []

        # Merge nearby hits into single context windows (avoid duplicate context)
        merged: list[tuple[int, int]] = []
        for idx in hits:
            start = max(0, idx - _CONTEXT_LINES)
            end   = min(len(lines) - 1, idx + _CONTEXT_LINES)
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], end)   # extend previous window
            else:
                merged.append((start, end))

        return ["\n".join(lines[s:e+1]) for s, e in merged]

    # ── Stage 4: LLM extracts structured data from small snippets ─────────────

    def _extract_credits(
        self,
        blocks: list[str],
        entry_type: str,
        doc: ParsedDocument,
    ) -> list[dict]:
        """
        One LLM call for all matched blocks combined (they're small).
        Returns list of {date, amount, line} dicts validated by Pydantic.
        """
        if not blocks:
            return []

        import litellm, json, re as _re
        from inditr.graph.llm import MODEL
        from .schemas.bank_statement import BankTransaction
        from pydantic import TypeAdapter

        combined = "\n---\n".join(blocks)

        prompt = f"""Extract all {entry_type} transactions from these bank statement snippets.

Each snippet is a few lines around one matching transaction.
Return a JSON array of objects. Each object:
{{
  "date": "DD-MM-YYYY or null",
  "particulars": "merged full description",
  "credit_amount": <number, rupees, no commas>,
  "debit_amount": null
}}

Rules:
- credit_amount: the amount credited (deposited) — the Deposits/Credit column value
- Only return entries where credit_amount > 0
- Merge multi-line particulars into one string
- Return [] if no credit entries found
- Return ONLY the JSON array, no explanation

Snippets:
---
{combined}
---

JSON array:"""

        try:
            resp = litellm.completion(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=4096,
            )
            raw = resp.choices[0].message.content or ""
            cleaned = _re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
            match = _re.search(r"\[[\s\S]*\]", cleaned)
            if not match:
                doc.parse_errors.append(f"{entry_type}: LLM returned no JSON array")
                return []
            try:
                rows = json.loads(match.group())
            except json.JSONDecodeError as je:
                doc.parse_errors.append(
                    f"{entry_type}: JSON truncated (increase max_tokens?) — {je}"
                )
                return []
            results = []
            for row in rows:
                try:
                    txn = BankTransaction.model_validate(row)
                    if txn.credit_amount and txn.credit_amount > 0:
                        results.append({
                            "date":   txn.date,
                            "amount": txn.credit_amount,
                            "line":   (txn.particulars or "")[:120],
                        })
                except Exception:
                    pass
            return results
        except Exception as exc:
            doc.parse_errors.append(f"{entry_type} extraction LLM call failed: {exc}")
            return []

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _extract_text(self, filepath: str, doc: ParsedDocument) -> tuple[str, int]:
        try:
            with pdfplumber.open(filepath) as pdf:
                pages = []
                for page in pdf.pages:
                    try:
                        pages.append(page.extract_text() or "")
                    except Exception as exc:
                        doc.parse_errors.append(f"Page extraction error: {exc}")
                return "\n".join(pages), len(pdf.pages)
        except Exception as exc:
            doc.parse_errors.append(f"Cannot open PDF: {exc}")
            return "", 0

    def _vision_fallback(self, filepath: str, doc: ParsedDocument) -> None:
        """Vision OCR fallback for image-based PDFs — only if text extraction failed."""
        try:
            from inditr.parsers.vision import parse_with_vision
            from pydantic import BaseModel as PydanticBase

            class BankSchema(PydanticBase):
                salary_credits: list[dict] = []
                fd_interest_total: float = 0.0

            vision_doc = parse_with_vision(filepath, "bank_statement", BankSchema)
            doc.fields.update(vision_doc.fields)
            doc.parse_errors.extend(vision_doc.parse_errors)
        except Exception as exc:
            doc.parse_errors.append(f"Vision fallback failed: {exc}")
