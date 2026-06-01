"""
AY 2026-27 deduction computation — pure Python, zero LLM.
"""
from __future__ import annotations
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from inditr.models.tax_data import Deductions


def compute_standard_deduction(regime: str) -> int:
    """Standard deduction: new regime ₹75,000 | old regime ₹50,000."""
    return 75_000 if regime == "new" else 50_000


def compute_hra_exemption(
    gross_salary: int,
    hra_received: int,
    rent_paid_monthly: int,
    is_metro: bool,
    basic_da: Optional[int] = None,
) -> int:
    """
    HRA exemption under Section 10(13A) — minimum of three conditions:
    1. Actual HRA received
    2. Rent paid − 10% of (Basic + DA)
    3. 50% (metro) / 40% (non-metro) of (Basic + DA)

    Uses basic_da if provided (correct per IT Act).
    Falls back to gross_salary as a conservative proxy when basic_da is unavailable.
    Only applicable under old regime. Returns 0 if rent_paid_monthly is 0.
    """
    if rent_paid_monthly <= 0 or hra_received <= 0:
        return 0

    base = basic_da if basic_da is not None else gross_salary
    annual_rent = rent_paid_monthly * 12
    city_pct = 0.50 if is_metro else 0.40

    condition_1 = hra_received
    condition_2 = max(0, annual_rent - int(0.10 * base))
    condition_3 = int(city_pct * base)

    return min(condition_1, condition_2, condition_3)


def validate_80c(declared: int) -> int:
    """Cap 80C deduction at ₹1,50,000."""
    return min(declared, 150_000)


def validate_80d(
    self_premium: int,
    parents_premium: int,
    self_is_senior: bool,
    parents_are_senior: bool,
) -> int:
    """
    80D limits:
    Self + family: ₹25,000 (₹50,000 if self/spouse is senior citizen)
    Parents: ₹25,000 (₹50,000 if parents are senior citizens)
    """
    self_limit = 50_000 if self_is_senior else 25_000
    parents_limit = 50_000 if parents_are_senior else 25_000
    return min(self_premium, self_limit) + min(parents_premium, parents_limit)


def validate_80tta_ttb(interest: int, is_senior: bool) -> int:
    """
    80TTA: savings bank interest up to ₹10,000 (non-seniors, old regime only)
    80TTB: all interest up to ₹50,000 (senior citizens, old regime only)
    """
    limit = 50_000 if is_senior else 10_000
    return min(interest, limit)


def compute_total_deductions(
    deductions: "Deductions",
    regime: str,
    age: int = 35,
    employer_nps_80ccd2: int = 0,
    professional_tax: int = 0,
) -> int:
    """
    Compute total deductions applicable for the given regime.

    employer_nps_80ccd2: Section 80CCD(2) employer NPS contribution (Budget 2025: 14% of
    salary for all employees). Available under BOTH regimes. Sourced from Form 16 via
    salary_income.employer_nps_80ccd2 — NOT a Chapter VI-A deduction.

    professional_tax: Section 16(iii) professional tax deduction. Old regime only.
    Capped at ₹2,500 by Article 276(2) of the Constitution. Sourced from Form 16.

    New regime: standard deduction + 80CCD(2) only.
    Old regime: standard deduction + 80CCD(2) + Section 16(iii) + all Chapter VI-A.
    Returns total deductions as integer.
    """
    std_deduction = compute_standard_deduction(regime)

    if regime == "new":
        # New regime: only standard deduction + employer NPS 80CCD(2).
        # Professional tax deduction is NOT available under the new regime.
        return std_deduction + employer_nps_80ccd2

    # Old regime — Section 16 deductions + employer NPS + Chapter VI-A
    is_senior = age >= 60
    total = std_deduction + employer_nps_80ccd2
    total += min(professional_tax, 2_500)            # Section 16(iii); Art 276(2) cap ₹2,500
    total += validate_80c(int(deductions.sec_80c))
    total += int(deductions.sec_80ccd_1b)            # capped in model at ₹50K; old regime only
    total += int(deductions.hra_exemption)            # pre-computed exemption
    total += int(deductions.sec_80d)                  # capped in model at ₹1L
    if is_senior:
        total += validate_80tta_ttb(int(deductions.sec_80ttb), is_senior=True)
    else:
        total += validate_80tta_ttb(int(deductions.sec_80tta), is_senior=False)
    total += min(int(deductions.home_loan_interest), 200_000)  # Section 24b cap ₹2L
    total += int(deductions.sec_80e)                           # Section 80E: education loan interest (no cap)
    total += int(deductions.sec_80g)                            # Section 80G: donations (declared net eligible amount)
    total += int(deductions.other_deductions)
    return total
