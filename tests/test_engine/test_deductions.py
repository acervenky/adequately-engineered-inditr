import pytest
from inditr.engine.deductions import (
    compute_standard_deduction,
    compute_hra_exemption,
    validate_80c,
    validate_80d,
    validate_80tta_ttb,
    compute_total_deductions,
)
from inditr.models.tax_data import Deductions


class TestStandardDeduction:
    def test_new_regime(self):
        assert compute_standard_deduction("new") == 75_000

    def test_old_regime(self):
        assert compute_standard_deduction("old") == 50_000


class TestHRAExemption:
    def test_metro_basic_case(self):
        # gross=600K, hra=120K, rent=15K/month (180K/yr), metro
        # c1=120K, c2=180K-60K=120K, c3=300K → min=120K
        result = compute_hra_exemption(600_000, 120_000, 15_000, is_metro=True)
        assert result == 120_000

    def test_non_metro(self):
        # gross=600K, hra=120K, rent=15K/month, non-metro (40%)
        # c1=120K, c2=120K, c3=240K → min=120K
        result = compute_hra_exemption(600_000, 120_000, 15_000, is_metro=False)
        assert result == 120_000

    def test_zero_rent(self):
        result = compute_hra_exemption(600_000, 120_000, 0, is_metro=True)
        assert result == 0

    def test_low_rent_limits_exemption(self):
        # gross=1M, hra=200K, rent=5K/month (60K/yr)
        # c1=200K, c2=60K-100K=negative→0, c3=500K → min=0
        result = compute_hra_exemption(1_000_000, 200_000, 5_000, is_metro=True)
        assert result == 0


class TestValidate80C:
    def test_under_limit(self):
        assert validate_80c(100_000) == 100_000

    def test_at_limit(self):
        assert validate_80c(150_000) == 150_000

    def test_over_limit_capped(self):
        assert validate_80c(200_000) == 150_000


class TestValidate80D:
    def test_non_senior(self):
        # self=20K limit 25K, parents=20K limit 25K → 40K
        assert validate_80d(20_000, 20_000, False, False) == 40_000

    def test_self_senior(self):
        # self=40K limit 50K, parents=0 → 40K
        assert validate_80d(40_000, 0, True, False) == 40_000

    def test_parents_senior(self):
        # parents=45K limit 50K → 45K + 0 = 45K
        assert validate_80d(0, 45_000, False, True) == 45_000

    def test_over_limit_capped(self):
        # self=30K capped at 25K, parents=60K capped at 50K → 75K
        assert validate_80d(30_000, 60_000, False, True) == 75_000


class TestValidate80TTa:
    def test_non_senior_under_limit(self):
        assert validate_80tta_ttb(8_000, False) == 8_000

    def test_non_senior_capped(self):
        assert validate_80tta_ttb(15_000, False) == 10_000

    def test_senior_80ttb_limit(self):
        assert validate_80tta_ttb(40_000, True) == 40_000

    def test_senior_80ttb_capped(self):
        assert validate_80tta_ttb(60_000, True) == 50_000


class TestComputeTotalDeductions:
    def test_new_regime_only_standard(self):
        d = Deductions(sec_80c=150_000, sec_80d=25_000, sec_80tta=10_000)
        result = compute_total_deductions(d, "new", age=35)
        assert result == 75_000  # only standard deduction

    def test_old_regime_full_deductions(self):
        d = Deductions(sec_80c=150_000, sec_80d=25_000, sec_80tta=10_000, sec_80ccd_1b=50_000)
        result = compute_total_deductions(d, "old", age=35)
        # std=50K + 80C=150K + 80CCD1B=50K + 80D=25K + 80TTA=10K = 285K
        assert result == 285_000
