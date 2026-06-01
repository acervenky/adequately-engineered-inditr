"""
AY 2026-27 income tax slab computation.
All values in INR (₹). All inputs/outputs are integers (paise truncated).
ZERO LLM calls — pure deterministic Python.
Budget 2025 / Finance Act 2025 rules (effective FY 2025-26 / AY 2026-27).
"""
from __future__ import annotations
from typing import Literal

from inditr.models.computation import SlabBreakdown

# ---------------------------------------------------------------------------
# Old Regime slab tables — unchanged across AYs
# ---------------------------------------------------------------------------
_OLD_SLABS_GENERAL = [
    (250_000,    0,         "0–2.5L",  0.00),
    (500_000,    250_000,   "2.5L–5L", 0.05),
    (1_000_000,  500_000,   "5L–10L",  0.20),
    (None,       1_000_000, ">10L",    0.30),
]

# Senior citizens (60 ≤ age < 80): basic exemption up to ₹3L
_OLD_SLABS_SENIOR = [
    (300_000,    0,         "0–3L",    0.00),
    (500_000,    300_000,   "3L–5L",   0.05),
    (1_000_000,  500_000,   "5L–10L",  0.20),
    (None,       1_000_000, ">10L",    0.30),
]

# Super senior citizens (80+): basic exemption up to ₹5L
_OLD_SLABS_SUPER_SENIOR = [
    (500_000,    0,         "0–5L",    0.00),
    (1_000_000,  500_000,   "5L–10L",  0.20),
    (None,       1_000_000, ">10L",    0.30),
]

# ---------------------------------------------------------------------------
# New Regime slab table — Budget 2025 / AY 2026-27 (age-independent)
# ---------------------------------------------------------------------------
_NEW_SLABS = [
    (400_000,    0,           "0–4L",    0.00),
    (800_000,    400_000,     "4L–8L",   0.05),
    (1_200_000,  800_000,     "8L–12L",  0.10),
    (1_600_000,  1_200_000,   "12L–16L", 0.15),
    (2_000_000,  1_600_000,   "16L–20L", 0.20),
    (2_400_000,  2_000_000,   "20L–24L", 0.25),
    (None,       2_400_000,   ">24L",    0.30),
]


def _apply_slabs(
    taxable_income: int,
    slabs: list[tuple],
) -> tuple[int, list[SlabBreakdown]]:
    """Generic slab applier. Returns (tax_amount, breakdown)."""
    tax = 0
    breakdown: list[SlabBreakdown] = []
    remaining = taxable_income
    for upper, lower, label, rate in slabs:
        if remaining <= 0:
            break
        if upper is None:
            taxable_in_slab = remaining
        else:
            taxable_in_slab = min(remaining, upper - lower)
        slab_tax = round(taxable_in_slab * rate)  # round to nearest rupee per IT Act
        if taxable_in_slab > 0:
            breakdown.append(
                SlabBreakdown(
                    slab_label=label,
                    rate=rate,
                    taxable_amount=taxable_in_slab,
                    tax=slab_tax,
                )
            )
        tax += slab_tax
        remaining -= taxable_in_slab
    return tax, breakdown


def compute_tax_old_regime(
    taxable_income: int, age: int
) -> tuple[int, list[SlabBreakdown]]:
    """
    Compute income tax under old regime.
    age: filer's age as of 31-Mar-2026 (AY 2026-27).
    Returns (basic_tax, slab_breakdown).
    """
    if age >= 80:
        slabs = _OLD_SLABS_SUPER_SENIOR
    elif age >= 60:
        slabs = _OLD_SLABS_SENIOR
    else:
        slabs = _OLD_SLABS_GENERAL
    return _apply_slabs(taxable_income, slabs)


def compute_tax_new_regime(
    taxable_income: int,
) -> tuple[int, list[SlabBreakdown]]:
    """
    Compute income tax under new regime (AY 2026-27 — Budget 2025 slabs).
    Age-independent. Returns (basic_tax, slab_breakdown).
    """
    return _apply_slabs(taxable_income, _NEW_SLABS)


# ---------------------------------------------------------------------------
# Surcharge — Section 2(1A) / Finance Act
# ---------------------------------------------------------------------------
# Surcharge thresholds: (income_above, normal_rate_old, normal_rate_new, cg_cap_rate)
# New regime: surcharge capped at 25% max (Budget 2023 amendment).
# Old regime: 37% for >₹5Cr.
# Sections 111A (equity STCG) and 112A (equity LTCG): surcharge always capped at 15%.
# Section 112 (property LTCG) and other CG: subject to normal surcharge rate.
_SURCHARGE_BRACKETS = [
    # (threshold,   old_rate, new_rate, cg_111a_112a_cap)
    (50_000_000,  0.37,     0.25,     0.15),   # >₹5Cr
    (20_000_000,  0.25,     0.25,     0.15),   # >₹2Cr
    (10_000_000,  0.15,     0.15,     0.15),   # >₹1Cr
    (5_000_000,   0.10,     0.10,     0.10),   # >₹50L
]


def apply_surcharge(
    basic_tax: int,
    cg_111a_tax: int,       # Section 111A equity STCG — surcharge capped at 15%
    cg_112a_tax: int,       # Section 112A equity LTCG — surcharge capped at 15%
    cg_other_tax: int,      # Other CG (property Sec 112, pre-Apr-2023 debt MF) — normal rate
    gross_income: int,
    regime: Literal["old", "new"] = "new",
) -> int:
    """
    Apply surcharge on income tax.
    - 111A (equity STCG) and 112A (equity LTCG): surcharge capped at 15%.
    - Other CG (property/112, pre-Apr-2023 debt MF): normal surcharge rate.
    - New regime: max surcharge 25% (no 37% bracket).
    - Old regime: 37% for income > ₹5Cr.
    Marginal relief applied: surcharge cannot exceed (gross_income - bracket_threshold).
    """
    normal_rate = 0.0
    cg_cap_rate = 0.0
    bracket_threshold = 0

    for threshold, old_rate, new_rate, cap in _SURCHARGE_BRACKETS:
        if gross_income > threshold:
            normal_rate = old_rate if regime == "old" else new_rate
            cg_cap_rate = cap
            bracket_threshold = threshold
            break

    if normal_rate == 0.0:
        return 0

    # 111A / 112A surcharge is always capped at 15% regardless of income level
    cg_111a_112a_rate = min(cg_cap_rate, 0.15)

    surcharge = (
        round(basic_tax * normal_rate)
        + round(cg_111a_tax * cg_111a_112a_rate)
        + round(cg_112a_tax * cg_111a_112a_rate)
        + round(cg_other_tax * normal_rate)
    )

    # Marginal relief: net tax increase due to entering this surcharge bracket
    # should not exceed the income above the bracket threshold.
    max_surcharge = gross_income - bracket_threshold
    return max(0, min(surcharge, max_surcharge))


def apply_cess(tax_after_surcharge: int) -> int:
    """Apply 4% Health & Education Cess on (tax + surcharge)."""
    return round(tax_after_surcharge * 0.04)


def apply_87a_rebate(
    basic_tax: int,
    total_taxable_income: int,
    regime: Literal["old", "new"],
) -> int:
    """
    Section 87A rebate — applies ONLY on slab-rate income tax.
    Per Budget 2025 / Finance Act 2025: rebate is NOT available on tax computed
    at special rates (capital gains u/s 111A, 112, 112A, etc.).

    Old regime: rebate up to ₹12,500 if total taxable income ≤ ₹5L.
    New regime: rebate up to ₹60,000 if total taxable income ≤ ₹12L (Budget 2025).
    total_taxable_income must include all income heads including capital gains.
    """
    if regime == "old":
        threshold = 500_000
        max_rebate = 12_500
    else:  # new
        threshold = 1_200_000
        max_rebate = 60_000

    if total_taxable_income <= threshold:
        return min(basic_tax, max_rebate)
    return 0


def apply_marginal_relief_87a(
    basic_tax: int,
    total_taxable_income: int,
    regime: Literal["old", "new"],
) -> int:
    """
    Marginal relief for Section 87A threshold.
    When total income exceeds the rebate threshold by a small amount, the slab tax
    (on normal-rate income) should not exceed the income above the threshold.
    This prevents a cliff where crossing ₹12L by ₹1 suddenly creates a large tax bill.

    Returns adjusted basic_tax after marginal relief.
    """
    threshold = 1_200_000 if regime == "new" else 500_000
    if total_taxable_income <= threshold:
        return basic_tax  # rebate will handle this; no marginal relief needed
    excess = total_taxable_income - threshold
    return min(basic_tax, excess)
