"""
Tests for Act 4 output nodes — pure Python nodes only.
"""
import pytest
from inditr.graph.nodes.output import compute_tax, build_outputs


def make_extracted_data():
    return {
        "salary_income": {
            "gross_salary": 700000,
            "tds_deducted": 20000,
            "basic": None,
            "hra_received": None,
            "hra_exemption": None,
            "lta": None,
            "other_allowances": 0.0,
            "perquisites": 0.0,
            "professional_tax": 0.0,
            "employer_name": None,
            "employer_tan": None,
        },
        "capital_gains": [],
        "other_income": 0.0,
        "house_property_income": 0.0,
        "deductions": {
            "sec_80c": 0.0,
            "sec_80d": 0.0,
            "sec_80tta": 0.0,
            "sec_80ccd_1b": 0.0,
            "hra_exemption": 0.0,
            "other_deductions": 0.0,
        },
        "advance_tax_paid": 0.0,
        "tds_total": 20000.0,
        "tcs_total": 0.0,
    }


def make_filer_profile():
    return {
        "pan": "ABCDE1234F",
        "name": "Test Filer",
        "date_of_birth": "1985-06-15",
        "employment_type": "salaried",
        "income_sources": ["salary"],
        "residential_status": "resident",
        "email": None,
        "mobile": None,
    }


class TestComputeTax:
    def test_computes_both_regimes(self):
        state = {
            "extracted_data": make_extracted_data(),
            "filer_profile": make_filer_profile(),
            "errors": [],
        }
        result = compute_tax(state)
        assert "computation" in result
        comp = result["computation"]
        assert "old_regime" in comp
        assert "new_regime" in comp
        assert comp["recommended_regime"] in ("old", "new")

    def test_missing_extracted_data_adds_error(self):
        state = {"extracted_data": None, "filer_profile": make_filer_profile(), "errors": []}
        result = compute_tax(state)
        assert len(result["errors"]) > 0

    def test_missing_filer_profile_adds_error(self):
        state = {"extracted_data": make_extracted_data(), "filer_profile": None, "errors": []}
        result = compute_tax(state)
        assert len(result["errors"]) > 0

    def test_computation_values_are_non_negative(self):
        state = {
            "extracted_data": make_extracted_data(),
            "filer_profile": make_filer_profile(),
            "errors": [],
        }
        result = compute_tax(state)
        comp = result["computation"]
        assert comp["new_regime"]["total_tax_liability"] >= 0
        assert comp["old_regime"]["total_tax_liability"] >= 0

    def test_savings_from_recommendation_non_negative(self):
        state = {
            "extracted_data": make_extracted_data(),
            "filer_profile": make_filer_profile(),
            "errors": [],
        }
        result = compute_tax(state)
        assert result["computation"]["savings_from_recommendation"] >= 0


class TestBuildOutputs:
    def _make_computation(self):
        from inditr.engine.regime import compare_regimes
        from inditr.models.tax_data import ExtractedTaxData, SalaryIncome
        from inditr.models.profile import FilerProfile, EmploymentType

        data = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=700000, tds_deducted=20000)
        )
        profile = FilerProfile(
            pan="ABCDE1234F",
            name="Test",
            date_of_birth="1985-06-15",
            employment_type=EmploymentType.SALARIED,
        )
        return compare_regimes(data, profile).model_dump()

    def test_build_outputs_creates_report(self):
        state = {
            "computation": self._make_computation(),
            "filer_profile": make_filer_profile(),
            "extracted_data": make_extracted_data(),
            "itr_form": "ITR-1",
            "errors": [],
        }
        result = build_outputs(state)
        assert "regime_report" in result
        assert "itr_json" in result
        rpt = result["regime_report"]
        # regime_report is now a structured dict with text_report + typed keys
        assert isinstance(rpt, dict)
        assert "INDITR TAX COMPUTATION SUMMARY" in rpt["text_report"]
        assert "old_tax" in rpt
        assert "new_tax" in rpt
        assert "recommendation" in rpt

    def test_build_outputs_report_has_disclaimer(self):
        state = {
            "computation": self._make_computation(),
            "filer_profile": make_filer_profile(),
            "extracted_data": make_extracted_data(),
            "itr_form": "ITR-1",
            "errors": [],
        }
        result = build_outputs(state)
        rpt = result["regime_report"]
        assert "DISCLAIMER" in rpt["text_report"]

    def test_build_outputs_itr_json_masked_pan(self):
        state = {
            "computation": self._make_computation(),
            "filer_profile": make_filer_profile(),
            "extracted_data": make_extracted_data(),
            "itr_form": "ITR-1",
            "errors": [],
        }
        result = build_outputs(state)
        pan_in_json = result["itr_json"]["PersonalInfo"]["PAN"]
        # Must be masked — should start with XXXXX
        assert pan_in_json.startswith("XXXXX")

    def test_no_computation_adds_error(self):
        state = {
            "computation": None,
            "filer_profile": make_filer_profile(),
            "extracted_data": {},
            "itr_form": "ITR-1",
            "errors": [],
        }
        result = build_outputs(state)
        assert len(result["errors"]) > 0
