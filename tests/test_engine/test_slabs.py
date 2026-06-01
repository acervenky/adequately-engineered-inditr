"""
Tests for AY 2026-27 slab computation, surcharge, cess, and 87A rebate.
"""
import pytest
from inditr.engine.slabs import (
    compute_tax_old_regime,
    compute_tax_new_regime,
    apply_surcharge,
    apply_cess,
    apply_87a_rebate,
    apply_marginal_relief_87a,
)


class TestOldRegimeSlabs:
    def test_zero_income(self):
        tax, breakdown = compute_tax_old_regime(0, age=35)
        assert tax == 0
        assert breakdown == []

    def test_below_exemption_limit(self):
        tax, _ = compute_tax_old_regime(200_000, age=35)
        assert tax == 0

    def test_exactly_at_exemption_limit(self):
        tax, _ = compute_tax_old_regime(250_000, age=35)
        assert tax == 0

    def test_income_in_5pct_slab(self):
        # 3L: (3L - 2.5L) * 5% = 2500
        tax, breakdown = compute_tax_old_regime(300_000, age=35)
        assert tax == 2_500
        assert any(b.rate == 0.05 for b in breakdown)

    def test_income_at_5L(self):
        # (5L - 2.5L) * 5% = 12500
        tax, _ = compute_tax_old_regime(500_000, age=35)
        assert tax == 12_500

    def test_income_at_10L(self):
        # 12500 + (10L - 5L) * 20% = 112500
        tax, _ = compute_tax_old_regime(1_000_000, age=35)
        assert tax == 112_500

    def test_income_above_10L(self):
        # 112500 + (12L - 10L) * 30% = 172500
        tax, _ = compute_tax_old_regime(1_200_000, age=35)
        assert tax == 172_500

    def test_senior_citizen_3L_exemption(self):
        # 60+: exemption up to 3L — income 3.5L: (3.5L - 3L) * 5% = 2500
        tax, _ = compute_tax_old_regime(350_000, age=62)
        assert tax == 2_500

    def test_super_senior_5L_exemption(self):
        # 80+: exemption up to 5L — income 5L = 0 tax
        tax, _ = compute_tax_old_regime(500_000, age=80)
        assert tax == 0

    def test_super_senior_above_5L(self):
        # 80+: (6L - 5L) * 20% = 20000
        tax, _ = compute_tax_old_regime(600_000, age=80)
        assert tax == 20_000


class TestNewRegimeSlabs:
    def test_zero_income(self):
        tax, _ = compute_tax_new_regime(0)
        assert tax == 0

    def test_below_4L(self):
        tax, _ = compute_tax_new_regime(250_000)
        assert tax == 0

    def test_at_4L(self):
        tax, _ = compute_tax_new_regime(400_000)
        assert tax == 0

    def test_income_7L(self):
        # 4L–7L: 3L * 5% = 15000
        tax, _ = compute_tax_new_regime(700_000)
        assert tax == 15_000

    def test_income_10L(self):
        # 4L–8L: 20000 + 8L–10L: 2L * 10% = 20000 → 40000
        tax, _ = compute_tax_new_regime(1_000_000)
        assert tax == 40_000

    def test_income_12L(self):
        # 20000 + 8L–12L: 4L * 10% = 40000 → 60000
        tax, _ = compute_tax_new_regime(1_200_000)
        assert tax == 60_000

    def test_income_15L(self):
        # 20000 + 40000 + 12L–15L: 3L * 15% = 45000 → 105000
        tax, _ = compute_tax_new_regime(1_500_000)
        assert tax == 105_000

    def test_income_20L(self):
        # 20000 + 40000 + 60000 + 16L–20L: 4L * 20% = 80000 → 200000
        tax, _ = compute_tax_new_regime(2_000_000)
        assert tax == 200_000


class TestSurcharge:
    def test_no_surcharge_below_50L(self):
        assert apply_surcharge(100_000, 0, 0, 0, 4_000_000, "new") == 0

    def test_10pct_surcharge_above_50L(self):
        # basic_tax 100K, gross 60L → 10% surcharge → 10000
        # marginal relief: 60L - 50L = 10L, surcharge 10K < 10L → no relief
        assert apply_surcharge(100_000, 0, 0, 0, 6_000_000, "new") == 10_000

    def test_15pct_surcharge_above_1cr(self):
        assert apply_surcharge(100_000, 0, 0, 0, 11_000_000, "new") == 15_000

    def test_25pct_surcharge_above_2cr_new_regime(self):
        # New regime: capped at 25% even for >2Cr
        assert apply_surcharge(100_000, 0, 0, 0, 21_000_000, "new") == 25_000

    def test_37pct_surcharge_above_5cr_old_regime(self):
        # Old regime: 37% for >5Cr
        assert apply_surcharge(100_000, 0, 0, 0, 51_000_000, "old") == 37_000

    def test_25pct_cap_new_regime_above_5cr(self):
        # New regime: >5Cr still capped at 25%
        assert apply_surcharge(100_000, 0, 0, 0, 51_000_000, "new") == 25_000

    def test_cg_111a_surcharge_capped_at_15pct(self):
        # Even at >2Cr, 111A surcharge is capped at 15% (not 25%)
        result = apply_surcharge(0, 100_000, 0, 0, 21_000_000, "new")
        assert result == 15_000

    def test_cg_112a_surcharge_capped_at_15pct(self):
        result = apply_surcharge(0, 0, 100_000, 0, 21_000_000, "new")
        assert result == 15_000

    def test_cg_property_normal_surcharge_rate(self):
        # Property LTCG (cg_other_tax) gets normal surcharge rate (25% at >2Cr new regime)
        result = apply_surcharge(0, 0, 0, 100_000, 21_000_000, "new")
        assert result == 25_000

    def test_cg_property_37pct_old_regime_above_5cr(self):
        # Property LTCG at >5Cr old regime: 37%
        result = apply_surcharge(0, 0, 0, 100_000, 51_000_000, "old")
        assert result == 37_000

    def test_marginal_relief_surcharge(self):
        # Income just above 50L threshold: surcharge should not exceed (income - 50L)
        # Income = 50L + 100, basic_tax = 1_000_000 (extreme to trigger relief)
        surcharge = apply_surcharge(1_000_000, 0, 0, 0, 5_000_100, "new")
        assert surcharge <= 100  # marginal relief: can't exceed income above 50L


class TestCess:
    def test_4pct_cess(self):
        assert apply_cess(100_000) == 4_000

    def test_cess_zero_input(self):
        assert apply_cess(0) == 0


class Test87ARebate:
    def test_old_regime_eligible(self):
        rebate = apply_87a_rebate(10_000, 400_000, "old")
        assert rebate == 10_000  # full tax rebated

    def test_old_regime_cap_at_12500(self):
        rebate = apply_87a_rebate(15_000, 450_000, "old")
        assert rebate == 12_500

    def test_old_regime_not_eligible(self):
        rebate = apply_87a_rebate(50_000, 600_000, "old")
        assert rebate == 0

    def test_new_regime_eligible(self):
        rebate = apply_87a_rebate(40_000, 1_000_000, "new")
        assert rebate == 40_000  # full tax rebated

    def test_new_regime_cap_at_60000(self):
        rebate = apply_87a_rebate(70_000, 1_200_000, "new")
        assert rebate == 60_000

    def test_new_regime_not_eligible(self):
        rebate = apply_87a_rebate(80_000, 1_250_000, "new")
        assert rebate == 0

    def test_new_regime_exactly_12L_taxable(self):
        # taxable 12L → rebate up to 60K
        tax, _ = compute_tax_new_regime(1_200_000)
        rebate = apply_87a_rebate(tax, 1_200_000, "new")
        assert tax == 60_000
        assert rebate == 60_000

    def test_new_regime_12L_plus_1_no_rebate(self):
        # taxable 12L+1 → no rebate
        tax, _ = compute_tax_new_regime(1_200_001)
        rebate = apply_87a_rebate(tax, 1_200_001, "new")
        assert rebate == 0


class TestMarginalRelief87A:
    def test_below_threshold_unchanged(self):
        # Income below threshold: no marginal relief (rebate handles it)
        assert apply_marginal_relief_87a(10_000, 1_000_000, "new") == 10_000

    def test_at_threshold_unchanged(self):
        assert apply_marginal_relief_87a(60_000, 1_200_000, "new") == 60_000

    def test_just_above_threshold_capped(self):
        # Income 12.1L, basic_tax 62K → capped at excess 1L (10K diff)
        assert apply_marginal_relief_87a(62_000, 1_210_000, "new") == 10_000

    def test_well_above_threshold_unchanged(self):
        # Income 15L, excess 3L. basic_tax 105K < 3L → no cap
        assert apply_marginal_relief_87a(105_000, 1_500_000, "new") == 105_000

    def test_old_regime_threshold(self):
        # Old regime threshold: 5L. Income 5.1L, basic_tax 15K → capped at 10K
        assert apply_marginal_relief_87a(15_000, 510_000, "old") == 10_000
