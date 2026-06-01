import pytest
from datetime import date
from inditr.engine.capital_gains import (
    classify_gain,
    compute_stcg_111a_tax,
    compute_ltcg_112a_tax,
    compute_ltcg_property_tax,
    compute_ltcg_other_tax,
    aggregate_gains,
)
from inditr.models.tax_data import CapitalGain, GainType, AssetType


class TestClassifyGain:
    def test_equity_held_over_year_is_ltcg(self):
        assert classify_gain("2023-01-01", "2024-06-01", AssetType.EQUITY) == "LTCG"

    def test_equity_held_under_year_is_stcg(self):
        assert classify_gain("2024-01-01", "2024-06-01", AssetType.EQUITY) == "STCG"

    def test_property_held_over_2yr_is_ltcg(self):
        assert classify_gain("2022-01-01", "2024-06-01", AssetType.IMMOVABLE_PROPERTY) == "LTCG"

    def test_property_held_under_2yr_is_stcg(self):
        assert classify_gain("2023-10-01", "2024-06-01", AssetType.IMMOVABLE_PROPERTY) == "STCG"

    def test_debt_mf_post_apr2023_always_slab(self):
        # Post-Apr-2023 debt MF: even if held 3 years, returns "SLAB"
        assert classify_gain("2023-06-01", "2026-07-01", AssetType.DEBT_MF) == "SLAB"

    def test_debt_mf_pre_apr2023_24months_is_ltcg(self):
        # Pre-Apr-2023 debt MF: 24-month threshold applies
        assert classify_gain("2021-01-01", "2023-02-01", AssetType.DEBT_MF) == "LTCG"

    def test_debt_mf_pre_apr2023_under_24months_is_stcg(self):
        assert classify_gain("2022-06-01", "2023-03-01", AssetType.DEBT_MF) == "STCG"

    def test_buyback_under_year_is_stcg(self):
        assert classify_gain("2025-06-01", "2025-10-01", AssetType.BUYBACK) == "STCG"

    def test_buyback_over_year_is_ltcg(self):
        assert classify_gain("2024-01-01", "2025-06-01", AssetType.BUYBACK) == "LTCG"


class TestComputeStcg111aTax:
    def test_stcg_20pct(self):
        assert compute_stcg_111a_tax(100_000) == 20_000

    def test_zero_stcg(self):
        assert compute_stcg_111a_tax(0) == 0


class TestComputeLtcg112aTax:
    def test_below_exemption_zero(self):
        # 1L < 1.25L exemption → 0
        assert compute_ltcg_112a_tax(100_000) == 0

    def test_above_exemption(self):
        # (2.25L - 1.25L) * 12.5% = 12500
        assert compute_ltcg_112a_tax(225_000) == 12_500

    def test_exactly_at_exemption(self):
        assert compute_ltcg_112a_tax(125_000) == 0


class TestComputeLtcgPropertyTax:
    def test_post_jul24_property_12_5pct(self):
        # 5L property LTCG: 5L * 12.5% = 62500
        assert compute_ltcg_property_tax(500_000) == 62_500

    def test_pre_jul24_property_indexed_20pct(self):
        # indexed gain 2L * 20% = 40000
        assert compute_ltcg_property_tax(0, 200_000) == 40_000

    def test_combined_property(self):
        # post: 3L * 12.5% = 37500; pre indexed: 1L * 20% = 20000; total = 57500
        assert compute_ltcg_property_tax(300_000, 100_000) == 57_500


class TestAggregateGains:
    def test_mixed_equity_gains(self):
        gains = [
            CapitalGain(gain_type=GainType.STCG, asset_type=AssetType.EQUITY,
                        sale_value=200_000, cost_of_acquisition=100_000, gain_amount=100_000),
            CapitalGain(gain_type=GainType.LTCG, asset_type=AssetType.EQUITY_MF,
                        sale_value=300_000, cost_of_acquisition=100_000, gain_amount=200_000,
                        section_112a=True),
        ]
        result = aggregate_gains(gains)
        assert result["stcg_equity_total"] == 100_000
        assert result["ltcg_equity_total"] == 200_000
        assert result["stcg_111a_tax"] == 20_000      # 100K * 20%
        assert result["ltcg_112a_tax"] == 9_375        # (200K-125K)*12.5%
        assert result["stcg_equity_tax"] == 20_000     # legacy alias
        assert result["ltcg_tax"] == 9_375             # legacy alias

    def test_empty_gains(self):
        result = aggregate_gains([])
        assert result["stcg_111a_tax"] == 0
        assert result["ltcg_112a_tax"] == 0
        assert result["ltcg_property_tax"] == 0
        assert result["slab_cg_total"] == 0

    def test_post_apr2023_debt_mf_to_slab(self):
        gains = [
            CapitalGain(gain_type=GainType.LTCG, asset_type=AssetType.DEBT_MF,
                        sale_value=200_000, cost_of_acquisition=100_000, gain_amount=100_000,
                        acquisition_date=date(2023, 6, 1)),
        ]
        result = aggregate_gains(gains)
        assert result["slab_cg_total"] == 100_000
        assert result["ltcg_112a_tax"] == 0
        assert result["ltcg_other_total"] == 0

    def test_pre_apr2023_debt_mf_ltcg(self):
        gains = [
            CapitalGain(gain_type=GainType.LTCG, asset_type=AssetType.DEBT_MF,
                        sale_value=200_000, cost_of_acquisition=100_000, gain_amount=100_000,
                        acquisition_date=date(2021, 1, 1)),
        ]
        result = aggregate_gains(gains)
        assert result["ltcg_other_total"] == 100_000
        assert result["ltcg_other_tax"] == 12_500  # 100K * 12.5%
        assert result["slab_cg_total"] == 0

    def test_property_ltcg_with_indexation_choice(self):
        # indexed_cost 3.5L on sale of 5L (gain 4L unindexed, 1.5L indexed)
        # 12.5% on 4L = 50000; 20% on 1.5L = 30000 → indexed is better
        gains = [
            CapitalGain(gain_type=GainType.LTCG, asset_type=AssetType.IMMOVABLE_PROPERTY,
                        sale_value=5_000_000, cost_of_acquisition=1_000_000, gain_amount=4_000_000,
                        acquisition_date=date(2020, 6, 1), indexed_cost=3_500_000),
        ]
        result = aggregate_gains(gains)
        assert result["ltcg_property_indexed_total"] == 1_500_000  # indexed gain
        assert result["ltcg_property_total"] == 0
        assert result["ltcg_property_tax"] == 300_000  # 1.5L * 20%

    def test_stcl_offsets_ltcg(self):
        # STCL 50K offsets LTCG property 2L
        gains = [
            CapitalGain(gain_type=GainType.STCG, asset_type=AssetType.EQUITY,
                        sale_value=50_000, cost_of_acquisition=100_000, gain_amount=-50_000),
            CapitalGain(gain_type=GainType.LTCG, asset_type=AssetType.IMMOVABLE_PROPERTY,
                        sale_value=300_000, cost_of_acquisition=100_000, gain_amount=200_000,
                        acquisition_date=date(2024, 8, 1)),
        ]
        result = aggregate_gains(gains)
        assert result["ltcg_property_total"] == 150_000   # 200K - 50K STCL
        assert result["stcg_equity_total"] == 0            # loss fully absorbed

    def test_buyback_treated_as_equity_stcg(self):
        gains = [
            CapitalGain(gain_type=GainType.STCG, asset_type=AssetType.BUYBACK,
                        sale_value=200_000, cost_of_acquisition=100_000, gain_amount=100_000),
        ]
        result = aggregate_gains(gains)
        assert result["stcg_equity_total"] == 100_000
        assert result["stcg_111a_tax"] == 20_000


class TestCIIConstant:
    """Verify CII FY 2025-26 = 376 is correct (CBDT notification 1 Jul 2025)."""

    def test_cii_fy2526_value(self):
        from inditr.engine import capital_gains as cg_module
        # CII constant used for indexed cost calculations
        assert cg_module._CII_FY2526 == 376

    def test_indexed_cost_uses_cii_376(self):
        """Property acquired in FY 2019-20 (CII 289), sold FY 2025-26 (CII 376).
        Indexed cost = purchase_cost * (376 / 289).
        The gain object should already carry pre-computed indexed_cost,
        but we verify aggregate_gains correctly uses it for the indexation choice."""
        # sale 50L, purchase 20L, indexed cost = 20L * (376/289) ≈ 26.02L
        purchase = 2_000_000
        sale = 5_000_000
        indexed_cost = round(purchase * (376 / 289))  # 2_601_384
        unindexed_gain = sale - purchase               # 3_000_000

        gains = [
            CapitalGain(
                gain_type=GainType.LTCG, asset_type=AssetType.IMMOVABLE_PROPERTY,
                sale_value=sale, cost_of_acquisition=purchase,
                gain_amount=unindexed_gain,
                acquisition_date=date(2019, 6, 1),  # pre-Jul-23-2024
                indexed_cost=indexed_cost,
            )
        ]
        result = aggregate_gains(gains)
        indexed_gain = sale - indexed_cost  # ~2_398_616

        # 12.5% on 30L = 375000; 20% on ~24L indexed = ~479723 → flat 12.5% is better
        tax_flat = unindexed_gain * 0.125
        tax_indexed = max(0, indexed_gain) * 0.20
        if tax_indexed <= tax_flat:
            assert result["ltcg_property_indexed_total"] == indexed_gain
            assert result["ltcg_property_total"] == 0
        else:
            assert result["ltcg_property_total"] == unindexed_gain
            assert result["ltcg_property_indexed_total"] == 0


class TestLTCGExemptionOnlyEquity:
    """₹1,25,000 LTCG exemption applies ONLY to 112A (equity/equity-MF), NOT property."""

    def test_property_ltcg_gets_no_exemption(self):
        gains = [
            CapitalGain(
                gain_type=GainType.LTCG, asset_type=AssetType.IMMOVABLE_PROPERTY,
                sale_value=2_000_000, cost_of_acquisition=1_000_000, gain_amount=1_000_000,
                acquisition_date=date(2024, 8, 1),  # post-Jul-23-2024: flat 12.5%
            )
        ]
        result = aggregate_gains(gains)
        # Full 10L taxed at 12.5% — no ₹1.25L exemption
        assert result["ltcg_property_tax"] == 125_000  # 10L * 12.5%
        assert result["ltcg_112a_tax"] == 0

    def test_equity_ltcg_gets_exemption(self):
        gains = [
            CapitalGain(
                gain_type=GainType.LTCG, asset_type=AssetType.EQUITY,
                sale_value=2_000_000, cost_of_acquisition=1_000_000, gain_amount=1_000_000,
                section_112a=True,
            )
        ]
        result = aggregate_gains(gains)
        # (10L - 1.25L exemption) = 8.75L * 12.5% = 109375
        assert result["ltcg_112a_tax"] == 109_375
        assert result["ltcg_property_tax"] == 0
