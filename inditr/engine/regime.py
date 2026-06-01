"""
Regime comparison orchestrator — pure function, zero LLM, no side effects.
AY 2026-27 / FY 2025-26 rules.
"""
from __future__ import annotations
from datetime import date

from inditr.models.computation import RegimeResult, TaxComputation
from inditr.models.tax_data import ExtractedTaxData
from inditr.models.profile import FilerProfile

from .slabs import (
    compute_tax_old_regime,
    compute_tax_new_regime,
    apply_surcharge,
    apply_cess,
    apply_87a_rebate,
    apply_marginal_relief_87a,
)
from .deductions import compute_total_deductions
from .capital_gains import (
    aggregate_gains,
    compute_stcg_111a_tax,
    compute_ltcg_112a_tax,
    compute_ltcg_property_tax,
    compute_ltcg_other_tax,
)


def _age_from_dob(dob: str) -> int:
    """Compute age as of 31-Mar-2026 (end of FY 2025-26 / AY 2026-27)."""
    dob_date = date.fromisoformat(dob)
    ref_date = date(2026, 3, 31)
    age = ref_date.year - dob_date.year
    if (ref_date.month, ref_date.day) < (dob_date.month, dob_date.day):
        age -= 1
    return age


def _compute_regime(
    data: ExtractedTaxData,
    filer: FilerProfile,
    regime: str,
) -> RegimeResult:
    """
    Compute complete tax liability for a single regime.
    regime: "old" | "new"
    """
    age = _age_from_dob(filer.date_of_birth)

    # ------------------------------------------------------------------
    # Gross income
    # ------------------------------------------------------------------
    gross_salary = int(data.salary_income.gross_salary) if data.salary_income else 0
    other_income = int(data.other_income)

    # House property: set-off rules differ by regime
    hp_income = int(data.house_property_income)
    if regime == "new":
        if hp_income < 0:
            hp_income = 0
    else:
        if hp_income < -200_000:
            hp_income = -200_000

    # Capital gains — aggregate and apply Sec 74 set-off rules
    cg = aggregate_gains(data.capital_gains)

    # Post-Apr-2023 debt MF and other-asset STCG are taxed at slab rates
    slab_cg_income = max(0, int(cg["stcg_other_total"]) + int(cg["slab_cg_total"]))

    gross_income = gross_salary + other_income + hp_income + slab_cg_income

    # ------------------------------------------------------------------
    # Deductions
    # ------------------------------------------------------------------
    employer_nps_80ccd2 = int(data.salary_income.employer_nps_80ccd2) if data.salary_income else 0
    professional_tax = int(data.salary_income.professional_tax) if data.salary_income else 0
    total_deductions = compute_total_deductions(
        data.deductions, regime, age,
        employer_nps_80ccd2=employer_nps_80ccd2,
        professional_tax=professional_tax,
    )
    taxable_income = max(0, gross_income - total_deductions)

    # ------------------------------------------------------------------
    # Basic slab tax
    # ------------------------------------------------------------------
    if regime == "old":
        basic_tax, slab_breakdown = compute_tax_old_regime(taxable_income, age)
    else:
        basic_tax, slab_breakdown = compute_tax_new_regime(taxable_income)

    # ------------------------------------------------------------------
    # Section 54 / 54EC / 54F — capital gains reinvestment exemptions
    # Available under BOTH regimes.
    #
    # FIX (minor): Apply to pre-Jul-2024 indexed property gains (taxed at 20%)
    # BEFORE post-Jul-2024 flat gains (12.5%) — this maximises tax saving for the
    # filer. The statute does not specify order; optimal interpretation is used.
    # ------------------------------------------------------------------
    sec_54ec_capped = min(int(data.deductions.sec_54ec_exemption), 5_000_000)  # cap at Rs.50L
    sec_54_total = (
        int(data.deductions.sec_54_exemption)
        + sec_54ec_capped
        + int(data.deductions.sec_54f_exemption)
    )

    ltcg_prop_indexed = int(cg["ltcg_property_indexed_total"])
    ltcg_prop_flat    = int(cg["ltcg_property_total"])
    sec54_rem = sec_54_total

    if sec54_rem > 0:
        # Reduce indexed (20%) bucket first — higher tax rate
        used = min(sec54_rem, ltcg_prop_indexed)
        ltcg_prop_indexed -= used
        sec54_rem -= used
        # Then flat (12.5%) bucket
        used = min(sec54_rem, ltcg_prop_flat)
        ltcg_prop_flat -= used

    # Working CG amounts after Sec-54 exemptions (before basic-exemption offset)
    stcg_111a = int(cg["stcg_equity_total"])
    ltcg_112a = int(cg["ltcg_equity_total"])
    ltcg_other = int(cg["ltcg_other_total"])

    # ------------------------------------------------------------------
    # 87A / surcharge threshold: "total income" = slab taxable + all CG
    # post Sec-54 exemption, BEFORE basic-exemption offset.
    # The basic-exemption offset reduces CG *tax*, not the income figure
    # used for the 87A threshold or surcharge bracket.
    # ------------------------------------------------------------------
    property_post54 = ltcg_prop_indexed + ltcg_prop_flat
    total_taxable_for_rebate = (
        taxable_income + stcg_111a + ltcg_112a + property_post54 + ltcg_other
    )

    # ------------------------------------------------------------------
    # Unexhausted basic exemption + unabsorbed HP loss -> offset special-rate CG
    #
    # FIX (critical):
    # - Provisos to Sec 111A(1), 112A(1), 112(1): resident individuals can apply
    #   unused basic exemption against special-rate CG before computing CG tax.
    # - Section 71: HP loss (up to Rs.2L cap) set off against CG income when it
    #   could not be fully absorbed by slab-rate income.
    #
    # Statutory application order: STCG 111A -> LTCG 112A -> property (20% first,
    # then 12.5%) -> other LTCG.
    # ------------------------------------------------------------------

    # Positive slab income before HP offset
    slab_positive = gross_salary + other_income + slab_cg_income  # always >= 0

    # HP loss not absorbed by positive slab income (old regime only)
    hp_loss = max(0, -hp_income)
    hp_unabsorbed = max(0, hp_loss - slab_positive)

    # Basic exemption not consumed by slab taxable income
    if regime == "new":
        _basic_exemption = 400_000
    elif age >= 80:
        _basic_exemption = 500_000
    elif age >= 60:
        _basic_exemption = 300_000
    else:
        _basic_exemption = 250_000
    unused_basic_exemption = max(0, _basic_exemption - taxable_income)

    cg_offset = hp_unabsorbed + unused_basic_exemption

    if cg_offset > 0:
        # STCG 111A first (statutory; also 20% rate)
        used = min(cg_offset, stcg_111a)
        stcg_111a -= used
        cg_offset -= used
        # LTCG 112A (12.5%; Rs.1.25L exempt applied inside compute fn)
        used = min(cg_offset, ltcg_112a)
        ltcg_112a -= used
        cg_offset -= used
        # Property: 20% (indexed) bucket before 12.5% (flat) bucket
        used = min(cg_offset, ltcg_prop_indexed)
        ltcg_prop_indexed -= used
        cg_offset -= used
        used = min(cg_offset, ltcg_prop_flat)
        ltcg_prop_flat -= used
        cg_offset -= used
        # Other LTCG (12.5%)
        used = min(cg_offset, ltcg_other)
        ltcg_other -= used

    # Compute final special-rate CG taxes on net (post-offset) amounts
    stcg_111a_tax     = compute_stcg_111a_tax(stcg_111a)
    ltcg_112a_tax     = compute_ltcg_112a_tax(ltcg_112a)
    property_ltcg_tax = compute_ltcg_property_tax(ltcg_prop_flat, ltcg_prop_indexed)
    ltcg_other_tax    = compute_ltcg_other_tax(ltcg_other)

    capital_gains_special_tax = (
        stcg_111a_tax + ltcg_112a_tax + property_ltcg_tax + ltcg_other_tax
    )

    # ------------------------------------------------------------------
    # Section 87A — rebate and marginal relief
    # Rebate applies ONLY on slab-rate tax (NOT on special-rate CG tax).
    # Per Finance Act 2025: 87A rebate barred on 111A/112/112A/115BBH.
    # ------------------------------------------------------------------

    # Marginal relief: slab tax capped at (total income - threshold) for income
    # just above the 87A threshold
    basic_tax = apply_marginal_relief_87a(basic_tax, total_taxable_for_rebate, regime)

    # 87A rebate — slab tax only
    rebate = apply_87a_rebate(basic_tax, total_taxable_for_rebate, regime)

    # ------------------------------------------------------------------
    # Surcharge — Section 2(1A)
    # Bracket determined by total income (post-deductions, incl. all CG
    # post Sec-54 exemption, before basic-exemption offset).
    # ------------------------------------------------------------------
    surcharge = apply_surcharge(
        basic_tax=basic_tax,
        cg_111a_tax=stcg_111a_tax,
        cg_112a_tax=ltcg_112a_tax,
        cg_other_tax=property_ltcg_tax + ltcg_other_tax,
        gross_income=total_taxable_for_rebate,
        regime=regime,
    )

    # ------------------------------------------------------------------
    # Assemble total tax liability
    # ------------------------------------------------------------------
    total_tax_before_cess = basic_tax + capital_gains_special_tax
    tax_after_rebate = max(0, total_tax_before_cess - rebate)
    tax_with_surcharge = tax_after_rebate + surcharge
    cess = apply_cess(tax_with_surcharge)
    total_tax_liability = tax_with_surcharge + cess

    # ------------------------------------------------------------------
    # TDS / advance tax reconciliation
    # ------------------------------------------------------------------
    tds_from_salary = int(data.salary_income.tds_deducted) if data.salary_income else 0
    tds_total = (
        int(data.tds_total)
        + int(data.advance_tax_paid)
        + int(data.tcs_total)
        + tds_from_salary
    )
    net_payable = total_tax_liability - tds_total

    return RegimeResult(
        regime=regime,
        gross_income=max(0, gross_income),  # floor at 0 for display; HP loss absorbed into taxable_income
        standard_deduction=75_000 if regime == "new" else 50_000,
        total_deductions=total_deductions,
        taxable_income=taxable_income,
        slab_breakdown=slab_breakdown,
        income_tax=basic_tax,
        surcharge=surcharge,
        health_education_cess=cess,
        rebate_87a=rebate,
        total_tax_liability=total_tax_liability,
        tds_tcs_advance_tax=tds_total,
        net_payable_refundable=net_payable,
    )


def compare_regimes(
    data: ExtractedTaxData,
    filer: FilerProfile,
) -> TaxComputation:
    """
    Pure function: compute both regimes and recommend the lower-tax option.
    Same inputs always produce same outputs. No LLM, no side effects.
    """
    old = _compute_regime(data, filer, "old")
    new = _compute_regime(data, filer, "new")

    if old.total_tax_liability <= new.total_tax_liability:
        recommended = "old"
        savings = new.total_tax_liability - old.total_tax_liability
        reason = (
            f"Old regime saves Rs.{savings:,.0f} due to deductions exceeding the "
            f"benefit of lower new-regime slabs."
        )
    else:
        recommended = "new"
        savings = old.total_tax_liability - new.total_tax_liability
        reason = (
            f"New regime saves Rs.{savings:,.0f} due to lower slab rates outweighing "
            f"old-regime deductions."
        )

    return TaxComputation(
        old_regime=old,
        new_regime=new,
        recommended_regime=recommended,
        savings_from_recommendation=savings,
        recommendation_reason=reason,
    )
