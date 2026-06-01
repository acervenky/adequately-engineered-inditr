import pytest
from pydantic import ValidationError
from inditr.models.tax_data import (
    SalaryIncome, CapitalGain, GainType, AssetType,
    Deductions, ExtractedTaxData,
)


class TestSalaryIncome:
    def test_valid(self):
        s = SalaryIncome(gross_salary=700000, tds_deducted=50000)
        assert s.gross_salary == 700000

    def test_negative_gross_raises(self):
        with pytest.raises(ValidationError):
            SalaryIncome(gross_salary=-1)


class TestCapitalGain:
    def test_valid_ltcg_equity(self):
        cg = CapitalGain(
            gain_type=GainType.LTCG,
            asset_type=AssetType.EQUITY,
            sale_value=200000,
            cost_of_acquisition=100000,
            gain_amount=100000,
            section_112a=True,
        )
        assert cg.ltcg_exempt_eligible is True

    def test_ltcg_property_not_exempt(self):
        cg = CapitalGain(
            gain_type=GainType.LTCG,
            asset_type=AssetType.IMMOVABLE_PROPERTY,
            sale_value=5000000,
            cost_of_acquisition=2000000,
            gain_amount=3000000,
        )
        assert cg.ltcg_exempt_eligible is False

    def test_stcg_not_exempt(self):
        cg = CapitalGain(
            gain_type=GainType.STCG,
            asset_type=AssetType.EQUITY,
            sale_value=200000,
            cost_of_acquisition=100000,
            gain_amount=100000,
        )
        assert cg.ltcg_exempt_eligible is False

    def test_negative_sale_value_raises(self):
        with pytest.raises(ValidationError):
            CapitalGain(
                gain_type=GainType.STCG,
                asset_type=AssetType.OTHER,
                sale_value=-1,
                cost_of_acquisition=0,
                gain_amount=-1,
            )


class TestDeductions:
    def test_valid(self):
        d = Deductions(sec_80c=100000, sec_80d=25000, sec_80tta=5000)
        assert d.sec_80c == 100000

    def test_80c_over_limit_raises(self):
        with pytest.raises(ValidationError):
            Deductions(sec_80c=150001)

    def test_80c_at_limit_passes(self):
        d = Deductions(sec_80c=150000)
        assert d.sec_80c == 150000

    def test_80tta_over_limit_raises(self):
        with pytest.raises(ValidationError):
            Deductions(sec_80tta=10001)

    def test_80ccd_1b_over_limit_raises(self):
        with pytest.raises(ValidationError):
            Deductions(sec_80ccd_1b=50001)

    def test_defaults_zero(self):
        d = Deductions()
        assert d.sec_80c == 0.0
        assert d.sec_80d == 0.0


class TestExtractedTaxData:
    def test_valid_empty(self):
        etd = ExtractedTaxData()
        assert etd.salary_income is None
        assert etd.capital_gains == []

    def test_with_salary(self):
        etd = ExtractedTaxData(salary_income=SalaryIncome(gross_salary=600000))
        assert etd.salary_income.gross_salary == 600000
