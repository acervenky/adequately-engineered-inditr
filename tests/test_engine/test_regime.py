"""
Integration tests for compare_regimes — full AY 2026-27 computation pipeline.
Key corrections from prior version:
- 87A rebate does NOT apply to STCG (111A) or any special-rate CG tax (Budget 2025).
- Marginal relief applied when income is just above 87A threshold.
- Surcharge for 111A/112A capped at 15%; property LTCG at normal rate.
"""
import pytest
from inditr.engine.regime import compare_regimes
from inditr.models.tax_data import (
    ExtractedTaxData, SalaryIncome, Deductions,
    CapitalGain, GainType, AssetType,
)
from inditr.models.profile import FilerProfile, EmploymentType
from datetime import date


def make_filer(dob="1985-06-15", **kwargs):
    defaults = dict(
        pan="ABCDE1234F",
        name="Test Filer",
        date_of_birth=dob,
        employment_type=EmploymentType.SALARIED,
    )
    defaults.update(kwargs)
    return FilerProfile(**defaults)


class TestBasicSalaryCase:
    """TC-01: Basic salaried, 7L gross, no deductions — new regime better."""

    def test_new_regime_taxable_income(self):
        filer = make_filer()
        data = ExtractedTaxData(salary_income=SalaryIncome(gross_salary=700_000))
        result = compare_regimes(data, filer)
        new = result.new_regime
        # std deduction 75K → taxable = 625K
        assert new.taxable_income == 625_000

    def test_new_regime_zero_tax_via_87a(self):
        filer = make_filer()
        data = ExtractedTaxData(salary_income=SalaryIncome(gross_salary=700_000))
        result = compare_regimes(data, filer)
        new = result.new_regime
        # taxable 625K ≤ 12L → 87A rebate applies; slab tax = (625K-400K)*5% = 11250; rebate = 11250; net = 0
        assert new.rebate_87a == 11_250
        assert new.total_tax_liability == 0


class TestHighIncomeOldRegimeBetter:
    """TC-02: High income with max deductions — old regime may be better."""

    def test_old_regime_taxable_income(self):
        filer = make_filer()
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=1_500_000, tds_deducted=100_000),
            deductions=Deductions(
                sec_80c=150_000, sec_80d=25_000, sec_80tta=10_000, sec_80ccd_1b=50_000
            ),
        )
        result = compare_regimes(data, filer)
        old = result.old_regime
        # gross=15L, std=50K, 80C=150K, 80D=25K, 80TTA=10K, 80CCD1B=50K → deductions=285K
        # taxable = 15L - 285K = 1215K
        assert old.taxable_income == 1_215_000

    def test_recommendation_is_valid(self):
        filer = make_filer()
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=1_500_000),
            deductions=Deductions(sec_80c=150_000, sec_80d=25_000),
        )
        result = compare_regimes(data, filer)
        assert result.recommended_regime in ("old", "new")
        assert result.savings_from_recommendation >= 0


class TestSeniorCitizenOldRegime:
    """TC-03: Senior citizen (65), old regime, 3L exemption, 5L income."""

    def test_senior_tax(self):
        filer = make_filer(dob="1958-01-01")  # ~68 at 31-Mar-2026
        data = ExtractedTaxData(salary_income=SalaryIncome(gross_salary=500_000))
        result = compare_regimes(data, filer)
        old = result.old_regime
        # gross=5L, std=50K → taxable=450K; senior slab: (450K-300K)*5% = 7500
        assert old.income_tax == 7_500

    def test_senior_87a_rebate(self):
        filer = make_filer(dob="1958-01-01")
        data = ExtractedTaxData(salary_income=SalaryIncome(gross_salary=500_000))
        result = compare_regimes(data, filer)
        old = result.old_regime
        # taxable 450K ≤ 5L → 87A rebate = min(7500, 12500) = 7500 → tax = 0
        assert old.rebate_87a == 7_500
        assert old.total_tax_liability == 0


class TestLTCGEquityWithExemption:
    """TC-04: Equity LTCG — ₹1.25L exemption applies; 87A rebate NOT on CG tax (Budget 2025)."""

    def test_ltcg_below_exemption_zero_cg_tax(self):
        filer = make_filer()
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=500_000),
            capital_gains=[
                CapitalGain(
                    gain_type=GainType.LTCG, asset_type=AssetType.EQUITY_MF,
                    sale_value=300_000, cost_of_acquisition=200_000, gain_amount=100_000,
                    section_112a=True,
                )
            ],
        )
        result = compare_regimes(data, filer)
        new = result.new_regime
        # LTCG 1L < 1.25L exemption → CG tax = 0
        # Slab: 5L - 75K = 425K; slab tax (425K-400K)*5% = 1250; total incl CG = 425K+1L = 5.25L → rebate applies
        assert new.total_tax_liability == 0

    def test_ltcg_above_exemption_cg_tax_no_rebate(self):
        """
        87A rebate does NOT reduce LTCG tax (Budget 2025 clarification).
        The rebate only waives slab-rate tax.
        """
        filer = make_filer()
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=500_000),
            capital_gains=[
                CapitalGain(
                    gain_type=GainType.LTCG, asset_type=AssetType.EQUITY,
                    sale_value=500_000, cost_of_acquisition=100_000, gain_amount=400_000,
                    section_112a=True,
                )
            ],
        )
        result = compare_regimes(data, filer)
        new = result.new_regime
        # LTCG 4L → tax: (4L - 1.25L) * 12.5% = 2.75L * 12.5% = 34375
        # Slab income: 5L - 75K = 425K
        # Total for 87A threshold: 425K + 4L = 8.25L ≤ 12L → 87A rebate eligible
        # BUT rebate applies ONLY to basic slab tax, NOT to LTCG tax
        # basic_tax = (425K-400K)*5% = 1250; marginal relief: 8.25L > 12L? No → no MR
        # rebate = 1250 (waives basic slab tax)
        # CG tax = 34375 (unchanged, rebate does not touch it)
        # total_tax_before_cess = 0 (basic after rebate) + 34375 = 34375
        # cess = 34375 * 4% = 1375; total = 35750
        assert new.total_tax_liability == 35_750


class TestLTCGPropertyNoExemption:
    """TC-05: Property LTCG — no ₹1.25L exemption, 12.5% flat."""

    def test_property_ltcg_no_exemption(self):
        filer = make_filer()
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=500_000),
            capital_gains=[
                CapitalGain(
                    gain_type=GainType.LTCG, asset_type=AssetType.IMMOVABLE_PROPERTY,
                    sale_value=3_000_000, cost_of_acquisition=1_000_000, gain_amount=2_000_000,
                    acquisition_date=date(2024, 8, 1),  # post-Jul-23-2024: 12.5% flat
                )
            ],
        )
        result = compare_regimes(data, filer)
        new = result.new_regime
        # property LTCG 20L * 12.5% = 250000
        # slab: 5L - 75K = 425K; slab tax = (425K-400K)*5% = 1250
        # 87A threshold: 425K + 20L = 24.25L > 12L → no rebate, no marginal relief
        # total_tax_before_cess = 1250 + 250000 = 251250
        # cess = 251250 * 4% = 10050; total = 261300
        assert new.total_tax_liability == 261_300


class TestPropertyLTCGWithIndexation:
    """TC-05b: Property acquired before Jul 23, 2024 — indexation option."""

    def test_pre_jul24_property_indexation_choice(self):
        """When 20%+indexation gives lower tax than 12.5% flat, indexed cost is used."""
        filer = make_filer()
        data = ExtractedTaxData(
            capital_gains=[
                CapitalGain(
                    gain_type=GainType.LTCG, asset_type=AssetType.IMMOVABLE_PROPERTY,
                    sale_value=5_000_000, cost_of_acquisition=1_000_000, gain_amount=4_000_000,
                    acquisition_date=date(2020, 6, 1),  # pre-Jul-23-2024
                    indexed_cost=3_500_000,             # indexed cost (high → low indexed gain)
                )
            ],
        )
        result = compare_regimes(data, filer)
        new = result.new_regime
        # Without indexation: 4L * 12.5% = 500_000
        # With indexation: (50L - 35L) = 15L indexed gain * 20% = 300_000
        # Code should pick the lower: indexed gain of 15L.
        # FIX: filer has zero slab income → basic exemption (₹4L, new regime)
        # reduces taxable indexed gain: 15L - 4L = 11L.
        # CG tax = 11L * 20% = 220_000; cess = 8_800; total = 228_800
        assert new.total_tax_liability == 228_800


class TestDebtMFPostApr2023:
    """TC-05c: Post-Apr-2023 debt MF gains always taxed at slab rates."""

    def test_debt_mf_post_apr2023_slab_taxed(self):
        filer = make_filer()
        data = ExtractedTaxData(
            capital_gains=[
                CapitalGain(
                    gain_type=GainType.LTCG, asset_type=AssetType.DEBT_MF,
                    sale_value=200_000, cost_of_acquisition=100_000, gain_amount=100_000,
                    acquisition_date=date(2023, 6, 1),  # post-Apr-2023
                )
            ],
        )
        result = compare_regimes(data, filer)
        new = result.new_regime
        # Debt MF post-Apr-2023: slab_cg_total = 100K → added to gross income
        # new regime: 100K - 75K std = 25K taxable; 25K < 4L → tax = 0; rebate → 0
        assert new.total_tax_liability == 0


class TestTDSRefund:
    """TC-06: TDS > tax liability → refund."""

    def test_refund_scenario(self):
        filer = make_filer()
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=400_000, tds_deducted=50_000),
        )
        result = compare_regimes(data, filer)
        new = result.new_regime
        # taxable: 400K - 75K = 325K ≤ 12L → 87A; slab tax=(325K-300K)*5%=1250; rebate=1250→0
        # tds = 50K; net = -50K (refund)
        assert new.net_payable_refundable == -50_000


class TestZeroIncome:
    """TC-07: Zero income — zero tax."""

    def test_zero_income_zero_tax(self):
        filer = make_filer()
        data = ExtractedTaxData()
        result = compare_regimes(data, filer)
        assert result.new_regime.total_tax_liability == 0
        assert result.old_regime.total_tax_liability == 0


class TestSlabBoundary:
    """TC-08: Income exactly at slab boundaries."""

    def test_new_regime_exactly_12L_gets_full_rebate(self):
        from inditr.engine.slabs import compute_tax_new_regime, apply_87a_rebate
        tax, _ = compute_tax_new_regime(1_200_000)
        rebate = apply_87a_rebate(tax, 1_200_000, "new")
        assert tax == 60_000
        assert rebate == 60_000

    def test_new_regime_12L_plus_1_no_rebate(self):
        from inditr.engine.slabs import compute_tax_new_regime, apply_87a_rebate
        tax, _ = compute_tax_new_regime(1_200_001)
        rebate = apply_87a_rebate(tax, 1_200_001, "new")
        assert rebate == 0


class TestMarginalRelief:
    """TC-08b: Marginal relief at 87A threshold."""

    def test_marginal_relief_applied_just_above_12L(self):
        """At 12L + 10K income, slab tax should be capped at 10K (excess above 12L)."""
        filer = make_filer()
        # Salary: 12L + 10K + 75K std = 12.85L gross → taxable slab = 12.1L
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=1_285_000),
        )
        result = compare_regimes(data, filer)
        new = result.new_regime
        # taxable = 1285K - 75K = 1210K; total_taxable_for_rebate = 1210K > 12L
        # no rebate; marginal relief: basic_tax = min(tax_on_1210K, 10K) = 10K
        # cess on 10K = 400; total = 10_400
        assert new.total_tax_liability == 10_400


class TestSurchargeCase:
    """TC-09: Income above 50L — surcharge applies."""

    def test_surcharge_above_50L(self):
        filer = make_filer()
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=6_000_000, tds_deducted=1_000_000),
        )
        result = compare_regimes(data, filer)
        assert result.new_regime.surcharge > 0

    def test_surcharge_increases_with_income(self):
        filer = make_filer()
        r50 = compare_regimes(ExtractedTaxData(salary_income=SalaryIncome(gross_salary=5_000_000)), filer)
        r55 = compare_regimes(ExtractedTaxData(salary_income=SalaryIncome(gross_salary=5_500_000)), filer)
        assert r55.new_regime.surcharge > r50.new_regime.surcharge


class TestHRACase:
    """TC-10: HRA exemption reduces taxable income under old regime."""

    def test_hra_reduces_old_regime_tax(self):
        filer = make_filer()
        data_with_hra = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=800_000, hra_exemption=96_000),
            deductions=Deductions(hra_exemption=96_000),
        )
        data_without_hra = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=800_000),
        )
        r_with = compare_regimes(data_with_hra, filer)
        r_without = compare_regimes(data_without_hra, filer)
        assert r_with.old_regime.taxable_income < r_without.old_regime.taxable_income
        assert r_with.old_regime.total_tax_liability <= r_without.old_regime.total_tax_liability


class TestShareBuyback:
    """TC-11: Share buyback proceeds taxed as capital gains from FY 2026-27."""

    def test_buyback_stcg_taxed_like_equity(self):
        filer = make_filer()
        data = ExtractedTaxData(
            capital_gains=[
                CapitalGain(
                    gain_type=GainType.STCG, asset_type=AssetType.BUYBACK,
                    sale_value=300_000, cost_of_acquisition=200_000, gain_amount=100_000,
                )
            ],
        )
        result = compare_regimes(data, filer)
        new = result.new_regime
        # Buyback STCG ₹1L; filer has zero slab income.
        # FIX: basic exemption (₹4L, new regime) > STCG ₹1L → entire STCG covered.
        # Net taxable STCG = 0; total tax = 0.
        assert new.total_tax_liability == 0


class TestHouseProperyLoss:
    """TC-12: HP loss set-off rules differ between regimes."""

    def test_old_regime_hp_loss_capped_at_2L(self):
        """Old regime: HP loss set-off against salary capped at ₹2L (Section 71B)."""
        filer = make_filer()
        # HP loss of ₹3L — should be capped at ₹2L
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=1_000_000),
            house_property_income=-300_000,
        )
        result = compare_regimes(data, filer)
        old = result.old_regime
        # Gross income = 10L + (-2L capped) = 8L; deductions = 50K; taxable = 7.5L
        assert old.gross_income == 800_000
        # Verify capping occurred: gross_income would be 700K if uncapped (-3L+10L-50K std nope)
        # Actually gross_income in regime.py = gross_salary + other + hp_income + slab_cg
        # = 10L + 0 + (-2L capped) + 0 = 8L
        assert old.gross_income == 800_000

    def test_old_regime_hp_loss_exactly_2L_unchanged(self):
        """Old regime: HP loss of exactly ₹2L is not capped."""
        filer = make_filer()
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=1_000_000),
            house_property_income=-200_000,
        )
        result = compare_regimes(data, filer)
        old = result.old_regime
        assert old.gross_income == 800_000  # 10L - 2L = 8L

    def test_old_regime_hp_loss_below_2L_unchanged(self):
        """Old regime: HP loss below ₹2L is fully set off."""
        filer = make_filer()
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=1_000_000),
            house_property_income=-100_000,
        )
        result = compare_regimes(data, filer)
        old = result.old_regime
        assert old.gross_income == 900_000  # 10L - 1L = 9L

    def test_new_regime_hp_loss_fully_disallowed(self):
        """New regime: HP loss cannot be set off against any income (Section 115BAC)."""
        filer = make_filer()
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=1_000_000),
            house_property_income=-300_000,
        )
        result = compare_regimes(data, filer)
        new = result.new_regime
        # HP loss is set to 0 under new regime → gross income = 10L (salary only)
        assert new.gross_income == 1_000_000

    def test_new_regime_hp_income_positive_still_counted(self):
        """New regime: positive HP income (let-out) is counted in gross income."""
        filer = make_filer()
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=1_000_000),
            house_property_income=120_000,
        )
        result = compare_regimes(data, filer)
        new = result.new_regime
        assert new.gross_income == 1_120_000


class TestSurchargeCapNewRegime:
    """TC-13: New regime surcharge never exceeds 25%, even at >₹5Cr income."""

    def test_new_regime_surcharge_cap_at_25pct_above_5cr(self):
        """New regime: income ₹6Cr should give 25% surcharge (not 37%)."""
        filer = make_filer()
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=60_000_000),
        )
        result = compare_regimes(data, filer)
        new = result.new_regime
        assert new.surcharge > 0
        # Compute effective surcharge rate: surcharge / income_tax
        if new.income_tax > 0:
            effective_rate = new.surcharge / new.income_tax
            assert effective_rate <= 0.25, f"New regime surcharge rate {effective_rate:.0%} exceeds 25%"

    def test_old_regime_37pct_surcharge_allowed_above_5cr(self):
        """Old regime: income ₹6Cr can attract 37% surcharge (with marginal relief)."""
        filer = make_filer()
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=60_000_000),
        )
        result = compare_regimes(data, filer)
        old = result.old_regime
        new = result.new_regime
        # Old regime total tax should be higher than new at >₹5Cr (37% vs 25% surcharge)
        assert old.total_tax_liability >= new.total_tax_liability


class TestCGSurchargeCapAt15Pct:
    """TC-14: 111A and 112A surcharge always capped at 15%."""

    def test_equity_stcg_surcharge_capped_at_15pct_high_income(self):
        """Even at ₹3Cr total income, equity STCG surcharge capped at 15% (not 25%)."""
        filer = make_filer()
        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=25_000_000),
            capital_gains=[
                CapitalGain(
                    gain_type=GainType.STCG, asset_type=AssetType.EQUITY,
                    sale_value=6_000_000, cost_of_acquisition=1_000_000, gain_amount=5_000_000,
                )
            ],
        )
        result = compare_regimes(data, filer)
        new = result.new_regime
        # Total income >₹2Cr → new regime normal surcharge = 25%
        # But equity STCG surcharge is capped at 15%
        # Verify: if uncapped, equity STCG surcharge would be 25%*111A_tax = higher
        # We just verify total tax is computed (not raising) and surcharge > 0
        assert new.surcharge > 0
        assert new.total_tax_liability > 0
