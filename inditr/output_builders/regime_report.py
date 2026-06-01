"""
Regime comparison JSON report builder — ZERO LLM.
"""
from __future__ import annotations
from typing import Any

from inditr.models.computation import TaxComputation, RegimeResult
from inditr.models.tax_data import ExtractedTaxData
from inditr.models.profile import FilerProfile

_DISCLAIMER = (
    "IndITR is an open-source tool for tax preparation assistance. "
    "It does not constitute professional tax advice. All computations must be "
    "verified by the user before filing. The authors assume no liability for "
    "errors, omissions, or penalties arising from use of this tool. "
    "When in doubt, consult a qualified Chartered Accountant."
)


def _mask_pan(pan: str) -> str:
    if len(pan) == 10:
        return f"XXXXX{pan[5:9]}X"
    return "XXXXXXXXXX"


def _regime_dict(r: RegimeResult, data: ExtractedTaxData) -> dict[str, Any]:
    from inditr.engine.capital_gains import aggregate_gains
    cg_summary = aggregate_gains(data.capital_gains)
    # Use pre-tax CG breakdown for display; total_tax_liability is the authoritative figure
    # (it already incorporates Sec 54/54EC/54F reductions computed in regime.py)
    cg_special_tax_display = (
        cg_summary["stcg_111a_tax"]
        + cg_summary["ltcg_112a_tax"]
        + cg_summary["ltcg_property_tax"]
        + cg_summary["ltcg_other_tax"]
    )
    # Reduce by 54/54EC/54F exemption impact for display accuracy
    d = data.deductions
    sec_54_total = min(
        int(d.sec_54_exemption) + min(int(d.sec_54ec_exemption), 5_000_000) + int(d.sec_54f_exemption),
        max(0, cg_summary["ltcg_property_total"] + cg_summary["ltcg_property_indexed_total"]),
    )
    if sec_54_total > 0 and (cg_summary["ltcg_property_total"] + cg_summary["ltcg_property_indexed_total"]) > 0:
        frac = sec_54_total / (cg_summary["ltcg_property_total"] + cg_summary["ltcg_property_indexed_total"])
        cg_special_tax_display = max(0, int(cg_special_tax_display - cg_summary["ltcg_property_tax"] * frac))
    effective_rate = (
        round(r.total_tax_liability / r.gross_income * 100, 2)
        if r.gross_income > 0 else 0.0
    )
    return {
        "gross_income": float(r.gross_income),
        "total_deductions": float(r.total_deductions),
        "taxable_income": float(r.taxable_income),
        "basic_tax": float(r.income_tax),
        "capital_gains_tax": float(cg_special_tax_display),
        "surcharge": float(r.surcharge),
        "cess": float(r.health_education_cess),
        "rebate_87a": float(r.rebate_87a),
        "total_tax": float(r.total_tax_liability),
        "tds_paid": float(r.tds_tcs_advance_tax),
        "refund_or_payable": float(r.net_payable_refundable),
        "effective_rate_pct": effective_rate,
        "slab_breakdown": [
            {
                "slab": s.slab_label,
                "rate_pct": round(s.rate * 100, 1),
                "taxable_amount": float(s.taxable_amount),
                "tax": float(s.tax),
            }
            for s in r.slab_breakdown
        ],
    }


def build_regime_report(
    computation: TaxComputation,
    data: ExtractedTaxData,
    profile: FilerProfile,
) -> dict[str, Any]:
    """
    Build regime comparison JSON report.
    ZERO LLM. Every field traced to TaxComputation / ExtractedTaxData.
    PAN masked as XXXXX####X.
    """
    return {
        "assessment_year": "AY 2026-27",
        "filer_pan": _mask_pan(profile.pan),
        "filer_name": profile.name,
        "old_regime": _regime_dict(computation.old_regime, data),
        "new_regime": _regime_dict(computation.new_regime, data),
        "recommendation": computation.recommended_regime,
        "savings": float(computation.savings_from_recommendation),
        "reason": computation.recommendation_reason,
        "disclaimer": _DISCLAIMER,
    }
