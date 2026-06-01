"""
Validation layer — runs after LLM extraction, before ParsedDocument is returned.

Python cross-checks: deterministic, fast, reliable.
    - Format validation (TAN, PAN regex)
    - Mathematical consistency between fields
    - Statutory limit checks (80C cap, standard deduction cap, etc.)

Fields whose confidence drops below 0.85 automatically go to human_doc_review.

No LLM reviewer: same model re-reading the same text adds no reliable signal.
The human_doc_review interrupt is the real verification gate.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_TAN_RE = re.compile(r"^[A-Z]{4}[0-9]{5}[A-Z]$")
_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
_ARITH_TOL = 0.05  # 5% tolerance for salary arithmetic cross-checks


# ── Result container ──────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    issues: list[str] = field(default_factory=list)
    confidence_adjustments: dict[str, float] = field(default_factory=dict)

    def flag(self, field_name: str, issue: str, new_confidence: float) -> None:
        """Lower confidence and record an issue for a field that failed a check."""
        self.issues.append(issue)
        existing = self.confidence_adjustments.get(field_name, 1.0)
        self.confidence_adjustments[field_name] = min(existing, new_confidence)

    def confirm(self, *field_names: str, boosted_confidence: float = 0.92) -> None:
        """
        Raise confidence for fields that passed a cross-check.

        LLM-extracted fields start at 0.80 (below the 0.85 human-review gate).
        When a Python cross-check mathematically confirms a field's value is
        internally consistent, we raise it to 0.92 so it proceeds to computation
        without requiring human confirmation.

        Only raises — never lowers (fields already flagged keep their lower score).
        """
        for name in field_names:
            existing = self.confidence_adjustments.get(name, 0.0)
            # Don't override a downward flag; only boost if currently unflagged (0.0 sentinel)
            # or already at a high level.
            if existing == 0.0 or existing >= boosted_confidence:
                self.confidence_adjustments[name] = boosted_confidence


# ── Helpers ───────────────────────────────────────────────────────────────────

def _within(a: float | None, b: float | None, tol: float = _ARITH_TOL) -> bool:
    if a is None or b is None:
        return True
    if b == 0:
        return abs(a) < 1.0
    return abs(a - b) / abs(b) <= tol


def _fmt(v: float | None) -> str:
    return f"Rs.{v:,.0f}" if v is not None else "N/A"


# ── Form 16 cross-checks ──────────────────────────────────────────────────────

def cross_check_form16(extracted) -> ValidationResult:
    """
    Deterministic cross-checks for Form16ExtractionSchema data.
    """
    result = ValidationResult()

    # ── Format checks ─────────────────────────────────────────────────────────
    if extracted.employer_tan and not _TAN_RE.match(extracted.employer_tan):
        result.flag("employer_tan",
            f"TAN '{extracted.employer_tan}' does not match AAAA99999A format", 0.3)
    elif extracted.employer_tan:
        result.confirm("employer_tan")

    if extracted.employee_pan and not _PAN_RE.match(extracted.employee_pan):
        result.flag("employee_pan",
            f"PAN '{extracted.employee_pan}' does not match AAAAA9999A format", 0.3)
    elif extracted.employee_pan:
        result.confirm("employee_pan")

    # Always confirm string-only identity fields (no math to verify)
    if extracted.employer_name:
        result.confirm("employer_name")
    if extracted.employee_name:
        result.confirm("employee_name")
    if extracted.financial_year:
        result.confirm("financial_year")

    # ── Gross salary sanity ────────────────────────────────────────────────────
    if extracted.gross_salary is not None:
        if extracted.gross_salary <= 0:
            result.flag("gross_salary", "Gross salary must be positive", 0.0)
        elif extracted.gross_salary < 10_000:
            result.flag("gross_salary",
                f"Gross salary {_fmt(extracted.gross_salary)} seems very low — verify", 0.6)
        else:
            result.confirm("gross_salary")

    # ── Standard deduction cap ─────────────────────────────────────────────────
    if extracted.standard_deduction is not None and extracted.standard_deduction > 75_000:
        result.flag("standard_deduction",
            f"Standard deduction {_fmt(extracted.standard_deduction)} exceeds Rs.75,000 cap", 0.3)
    elif extracted.standard_deduction is not None:
        result.confirm("standard_deduction")

    # ── TDS cannot exceed gross salary ─────────────────────────────────────────
    if extracted.tds_deducted is not None and extracted.gross_salary is not None:
        if extracted.tds_deducted > extracted.gross_salary:
            result.flag("tds_deducted",
                f"TDS {_fmt(extracted.tds_deducted)} exceeds gross salary "
                f"{_fmt(extracted.gross_salary)} — impossible", 0.1)
        else:
            # TDS effective rate >40% is extremely rare for salary income
            if extracted.gross_salary > 0:
                rate = extracted.tds_deducted / extracted.gross_salary
                if rate > 0.40:
                    result.flag("tds_deducted",
                        f"TDS rate {rate:.1%} of gross salary is unusually high (>40%) — verify", 0.5)
                else:
                    result.confirm("tds_deducted")

    # ── Net taxable salary arithmetic ──────────────────────────────────────────
    if (extracted.gross_salary is not None and extracted.net_taxable_salary is not None
            and extracted.standard_deduction is not None):
        expected = (
            extracted.gross_salary
            - (extracted.standard_deduction or 0)
            - (extracted.professional_tax or 0)
            - (extracted.hra_exemption or 0)
            - (extracted.entertainment_allowance or 0)
        )
        if not _within(extracted.net_taxable_salary, expected):
            result.flag("net_taxable_salary",
                f"Net taxable {_fmt(extracted.net_taxable_salary)} doesn't match "
                f"gross minus deductions ~{_fmt(expected)} (>{_ARITH_TOL:.0%} difference)", 0.6)
        else:
            result.confirm("net_taxable_salary", "professional_tax", "hra_exemption")

    # ── Total taxable income arithmetic ────────────────────────────────────────
    if (extracted.net_taxable_salary is not None and extracted.total_taxable_income is not None
            and extracted.total_chapter_via is not None):
        expected_tti = extracted.net_taxable_salary - extracted.total_chapter_via
        if not _within(extracted.total_taxable_income, expected_tti):
            result.flag("total_taxable_income",
                f"Total taxable income {_fmt(extracted.total_taxable_income)} doesn't match "
                f"net salary minus Chapter VI-A ~{_fmt(expected_tti)}", 0.6)
        else:
            result.confirm("total_taxable_income", "total_chapter_via")

    # ── Chapter VI-A cap ───────────────────────────────────────────────────────
    if extracted.total_chapter_via is not None and extracted.total_chapter_via > 400_000:
        result.flag("total_chapter_via",
            f"Chapter VI-A {_fmt(extracted.total_chapter_via)} seems very high (>Rs.4L) — verify", 0.5)

    # ── 80C statutory limit ────────────────────────────────────────────────────
    if extracted.deduction_80c is not None and extracted.deduction_80c > 150_000:
        result.flag("deduction_80c",
            f"80C deduction {_fmt(extracted.deduction_80c)} exceeds Rs.1,50,000 limit", 0.2)
    elif extracted.deduction_80c is not None:
        result.confirm("deduction_80c")

    # ── 80CCD(1B) statutory limit ──────────────────────────────────────────────
    if extracted.deduction_80ccd1b is not None and extracted.deduction_80ccd1b > 50_000:
        result.flag("deduction_80ccd1b",
            f"80CCD(1B) {_fmt(extracted.deduction_80ccd1b)} exceeds Rs.50,000 limit", 0.2)
    elif extracted.deduction_80ccd1b is not None:
        result.confirm("deduction_80ccd1b")

    # ── Part A vs Part B TDS consistency ──────────────────────────────────────
    # (tighter tolerance — same figure appears in two representations)
    if (extracted.total_tds_deposited is not None and extracted.tds_deducted is not None):
        if not _within(extracted.total_tds_deposited, extracted.tds_deducted, tol=0.02):
            result.flag("tds_deducted",
                f"Part A TDS {_fmt(extracted.total_tds_deposited)} vs "
                f"Part B TDS {_fmt(extracted.tds_deducted)} — mismatch >2%", 0.5)
        else:
            result.confirm("total_tds_deposited")

    return result
