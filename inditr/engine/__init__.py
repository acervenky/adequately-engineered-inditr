from .slabs import (
    compute_tax_old_regime,
    compute_tax_new_regime,
    apply_surcharge,
    apply_cess,
    apply_87a_rebate,
    apply_marginal_relief_87a,
)
from .deductions import (
    compute_standard_deduction,
    compute_hra_exemption,
    validate_80c,
    validate_80d,
    validate_80tta_ttb,
    compute_total_deductions,
)
from .capital_gains import (
    classify_gain,
    compute_stcg_111a_tax,
    compute_ltcg_112a_tax,
    compute_ltcg_property_tax,
    compute_ltcg_other_tax,
    aggregate_gains,
)
from .tds import reconcile_tds
from .regime import compare_regimes

__all__ = [
    "compute_tax_old_regime", "compute_tax_new_regime",
    "apply_surcharge", "apply_cess", "apply_87a_rebate", "apply_marginal_relief_87a",
    "compute_standard_deduction", "compute_hra_exemption",
    "validate_80c", "validate_80d", "validate_80tta_ttb", "compute_total_deductions",
    "classify_gain",
    "compute_stcg_111a_tax", "compute_ltcg_112a_tax",
    "compute_ltcg_property_tax", "compute_ltcg_other_tax",
    "aggregate_gains",
    "reconcile_tds",
    "compare_regimes",
]
