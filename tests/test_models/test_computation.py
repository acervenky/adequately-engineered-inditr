import pytest
from pydantic import ValidationError
from inditr.models.computation import SlabBreakdown, RegimeResult, TaxComputation


def make_regime_result(regime="new", **kwargs):
    defaults = dict(
        regime=regime,
        gross_income=700000,
        standard_deduction=75000,
        total_deductions=75000,
        taxable_income=625000,
        income_tax=25000,
        health_education_cess=1000,
        rebate_87a=0,
        total_tax_liability=26000,
        net_payable_refundable=-4000,
    )
    defaults.update(kwargs)
    return RegimeResult(**defaults)


class TestSlabBreakdown:
    def test_valid(self):
        s = SlabBreakdown(slab_label="3L–6L", rate=0.05, taxable_amount=300000, tax=15000)
        assert s.tax == 15000

    def test_negative_tax_raises(self):
        with pytest.raises(ValidationError):
            SlabBreakdown(slab_label="0–3L", rate=0.0, taxable_amount=300000, tax=-1)


class TestRegimeResult:
    def test_valid_new_regime(self):
        r = make_regime_result("new")
        assert r.regime == "new"

    def test_valid_old_regime(self):
        r = make_regime_result("old", standard_deduction=50000, total_deductions=50000)
        assert r.regime == "old"

    def test_invalid_regime_literal(self):
        with pytest.raises(ValidationError):
            make_regime_result("invalid_regime")

    def test_negative_gross_income_raises(self):
        with pytest.raises(ValidationError):
            make_regime_result(gross_income=-1)


class TestTaxComputation:
    def test_valid(self):
        old = make_regime_result("old", standard_deduction=50000, total_deductions=200000)
        new = make_regime_result("new")
        tc = TaxComputation(
            old_regime=old,
            new_regime=new,
            recommended_regime="new",
            savings_from_recommendation=5000,
            recommendation_reason="New regime saves ₹5,000 in taxes.",
        )
        assert tc.recommended_regime == "new"

    def test_invalid_recommended_regime(self):
        old = make_regime_result("old", standard_deduction=50000, total_deductions=200000)
        new = make_regime_result("new")
        with pytest.raises(ValidationError):
            TaxComputation(
                old_regime=old,
                new_regime=new,
                recommended_regime="both",
                savings_from_recommendation=0,
                recommendation_reason="test",
            )
