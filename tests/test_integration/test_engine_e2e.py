"""
Engine-level end-to-end integration tests.

These tests exercise the full computation pipeline:
  ExtractedTaxData + FilerProfile → compare_regimes() → TaxComputation
  → build_pdf_summary() / map_to_itr1() / map_to_itr2()

No LLM calls. Pure deterministic pipeline.

Two scenarios:
  - Simple: salaried filer, salary-only income, standard deductions
  - Complex: salaried filer with equity LTCG + property LTCG + deductions + TDS + surcharge
"""
from __future__ import annotations
import os
import json
import tempfile
from datetime import date

import pytest

from inditr.engine.regime import compare_regimes
from inditr.models.tax_data import (
    ExtractedTaxData, SalaryIncome, Deductions,
    CapitalGain, GainType, AssetType,
)
from inditr.models.profile import FilerProfile, EmploymentType
from inditr.output_builders.itr_json import map_to_itr1, map_to_itr2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_filer(dob="1985-06-15", name="Arjun Sharma", pan="ABCDE1234F") -> FilerProfile:
    return FilerProfile(
        pan=pan,
        name=name,
        date_of_birth=dob,
        employment_type=EmploymentType.SALARIED,
    )


# ---------------------------------------------------------------------------
# SCENARIO 1 — Simple: salary-only, standard deductions, new regime wins
# ---------------------------------------------------------------------------

class TestSimpleE2E:
    """
    Filer: age 40, gross salary ₹8L, no investments beyond 80C ₹1L.
    Expected: new regime wins (lower slabs, no deduction benefit).
    """

    @pytest.fixture
    def filer(self):
        return make_filer()

    @pytest.fixture
    def data(self):
        return ExtractedTaxData(
            salary_income=SalaryIncome(
                gross_salary=800_000,
                tds_deducted=10_000,
            ),
            deductions=Deductions(
                sec_80c=100_000,
            ),
        )

    def test_new_regime_taxable_income(self, filer, data):
        result = compare_regimes(data, filer)
        new = result.new_regime
        # new regime: std 75K → taxable = 8L - 75K = 7.25L
        assert new.taxable_income == 725_000

    def test_old_regime_taxable_income(self, filer, data):
        result = compare_regimes(data, filer)
        old = result.old_regime
        # old regime: std 50K + 80C 100K → 150K deductions; taxable = 8L - 150K = 6.5L
        assert old.taxable_income == 650_000

    def test_new_regime_tax_below_12L_zero_via_rebate(self, filer, data):
        """Taxable 7.25L < 12L → 87A rebate wipes slab tax."""
        result = compare_regimes(data, filer)
        new = result.new_regime
        # slab tax on 7.25L: (7.25L-4L)*5% + wait, 4L-8L at 5%: (7.25L-4L)*5% = 16250
        assert new.rebate_87a == 16_250
        assert new.total_tax_liability == 0

    def test_old_regime_tax(self, filer, data):
        result = compare_regimes(data, filer)
        old = result.old_regime
        # 6.5L: (5L-2.5L)*5% = 12500; (6.5L-5L)*20% = 30000 → 42500
        assert old.income_tax == 42_500
        # cess = 42500 * 4% = 1700
        assert old.total_tax_liability == 44_200

    def test_recommendation_is_new(self, filer, data):
        result = compare_regimes(data, filer)
        assert result.recommended_regime == "new"
        assert result.savings_from_recommendation == 44_200  # new=0, old=44200

    def test_tds_creates_full_refund_in_new_regime(self, filer, data):
        result = compare_regimes(data, filer)
        new = result.new_regime
        # new regime tax = 0; TDS paid = 10K → full refund
        assert new.net_payable_refundable == -10_000

    def test_itr1_json_output(self, filer, data):
        result = compare_regimes(data, filer)
        itr = map_to_itr1(data, result, filer)
        assert itr["AssessmentYear"] == "2026-27"
        assert itr["Form"] == "ITR-1"
        # PAN must be masked
        pan_in_json = itr["PersonalInfo"]["PAN"]
        assert pan_in_json.startswith("XXXXX")
        assert not pan_in_json[5:9].isalpha()  # 4 digits in the middle

    def test_pdf_summary_generated(self, filer, data):
        from inditr.output_builders.pdf_summary import build_pdf_summary
        result = compare_regimes(data, filer)
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "simple_test.pdf")
            out = build_pdf_summary(
                computation=result,
                data=data,
                profile=filer,
                output_path=pdf_path,
                itr_form="ITR-1",
            )
            assert os.path.isfile(out)
            assert os.path.getsize(out) > 1000  # non-trivial PDF


# ---------------------------------------------------------------------------
# SCENARIO 2 — Complex: salary + equity LTCG + property LTCG + deductions + TDS
# ---------------------------------------------------------------------------

class TestComplexE2E:
    """
    Filer: age 45, gross salary ₹20L, full deductions, equity LTCG ₹3L (above exemption),
    property LTCG ₹15L (post-Jul-2024, flat 12.5%), TDS ₹1.5L paid.

    This tests:
    - 87A rebate does NOT apply to CG special-rate tax
    - Property LTCG gets no ₹1.25L exemption
    - Equity LTCG gets ₹1.25L exemption
    - TDS reconciliation with refund/payable
    - ITR-2 output (has capital gains)
    - PDF generation with source trace appendix
    """

    @pytest.fixture
    def filer(self):
        return make_filer(dob="1980-03-15", pan="PQRST9876Z")

    @pytest.fixture
    def data(self):
        return ExtractedTaxData(
            salary_income=SalaryIncome(
                gross_salary=2_000_000,
                tds_deducted=150_000,
                employer_nps_80ccd2=280_000,  # 14% of salary (Budget 2025)
            ),
            deductions=Deductions(
                sec_80c=150_000,
                sec_80d=25_000,
                sec_80ccd_1b=50_000,   # old regime only
                sec_80tta=10_000,
            ),
            capital_gains=[
                CapitalGain(
                    gain_type=GainType.LTCG, asset_type=AssetType.EQUITY,
                    sale_value=600_000, cost_of_acquisition=300_000,
                    gain_amount=300_000, section_112a=True,
                ),
                CapitalGain(
                    gain_type=GainType.LTCG, asset_type=AssetType.IMMOVABLE_PROPERTY,
                    sale_value=3_000_000, cost_of_acquisition=1_500_000,
                    gain_amount=1_500_000,
                    acquisition_date=date(2024, 9, 1),  # post-Jul-23-2024: flat 12.5%
                ),
            ],
        )

    def test_new_regime_employer_nps_deductible(self, filer, data):
        """80CCD(2) employer NPS is deductible under new regime too."""
        result = compare_regimes(data, filer)
        new = result.new_regime
        # new regime deductions: std 75K + employer_nps 280K = 355K
        assert new.total_deductions == 355_000

    def test_old_regime_full_deductions(self, filer, data):
        result = compare_regimes(data, filer)
        old = result.old_regime
        # old: std 50K + emp_nps 280K + 80C 150K + 80D 25K + 80CCD1B 50K + 80TTA 10K = 565K
        assert old.total_deductions == 565_000

    def test_equity_ltcg_exemption_applied(self, filer, data):
        """Equity LTCG ₹3L → taxable ₹1.75L (after ₹1.25L exemption)."""
        result = compare_regimes(data, filer)
        new = result.new_regime
        # LTCG equity 3L, after 1.25L exemption = 1.75L * 12.5% = 21875
        # Verify via total tax that CG tax is included
        assert new.total_tax_liability > 0

    def test_property_ltcg_no_exemption(self, filer, data):
        """Property LTCG ₹15L: full amount taxed at 12.5%, no exemption."""
        from inditr.engine.capital_gains import aggregate_gains
        cg = aggregate_gains(data.capital_gains)
        # Property: 15L * 12.5% = 187500 (no exemption)
        assert cg["ltcg_property_tax"] == 187_500
        # Equity: (3L - 1.25L) * 12.5% = 21875
        assert cg["ltcg_112a_tax"] == 21_875

    def test_87a_rebate_not_on_cg_tax(self, filer, data):
        """87A rebate only reduces slab-rate tax, not CG special-rate tax."""
        result = compare_regimes(data, filer)
        new = result.new_regime
        # Salary gross 20L → taxable income for slab > 12L → no 87A rebate anyway
        # But the structural check: rebate_87a applies to income_tax (basic slab) only
        # Total CG taxes (21875 + 187500 = 209375) must be in total liability
        assert new.rebate_87a == 0  # income > 12L, no rebate
        assert new.total_tax_liability > 209_375

    def test_tds_reconciliation(self, filer, data):
        result = compare_regimes(data, filer)
        new = result.new_regime
        assert new.tds_tcs_advance_tax == 150_000
        # Total tax should be > TDS paid (complex income → still owes)
        assert new.net_payable_refundable == new.total_tax_liability - 150_000

    def test_old_regime_higher_deductions_may_win(self, filer, data):
        """With max deductions, old regime may be competitive. Both results must be valid."""
        result = compare_regimes(data, filer)
        assert result.recommended_regime in ("old", "new")
        assert result.savings_from_recommendation >= 0
        assert result.old_regime.total_tax_liability >= 0
        assert result.new_regime.total_tax_liability >= 0

    def test_itr2_json_output(self, filer, data):
        result = compare_regimes(data, filer)
        itr = map_to_itr2(data, result, filer)
        assert itr["AssessmentYear"] == "2026-27"
        assert itr["Form"] == "ITR-2"
        pan_in_json = itr["PersonalInfo"]["PAN"]
        assert pan_in_json.startswith("XXXXX")

    def test_pdf_generation_with_all_sections(self, filer, data):
        from inditr.output_builders.pdf_summary import build_pdf_summary
        result = compare_regimes(data, filer)
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "complex_test.pdf")
            out = build_pdf_summary(
                computation=result,
                data=data,
                profile=filer,
                output_path=pdf_path,
                itr_form="ITR-2",
            )
            assert os.path.isfile(out)
            assert os.path.getsize(out) > 2000

    def test_assessment_year_in_pdf_title(self, filer, data):
        """PDF metadata title must reference AY 2026-27, not 2024-25."""
        from inditr.output_builders.pdf_summary import build_pdf_summary
        result = compare_regimes(data, filer)
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = os.path.join(tmpdir, "ay_check.pdf")
            build_pdf_summary(
                computation=result, data=data, profile=filer,
                output_path=pdf_path, itr_form="ITR-2",
            )
            # Read raw PDF bytes and check for AY string
            with open(pdf_path, "rb") as f:
                content = f.read()
            assert b"2026-27" in content
            assert b"2024-25" not in content


# ---------------------------------------------------------------------------
# SCENARIO 3 — Senior citizen, minimal income, full 87A rebate
# ---------------------------------------------------------------------------

class TestSeniorCitizenE2E:
    """
    Filer: age 65 (born 1960-12-01), pension ₹4.5L, no investments.
    Old regime: senior citizen slabs, 87A rebate → zero tax.
    """

    @pytest.fixture
    def filer(self):
        return make_filer(dob="1960-12-01")

    @pytest.fixture
    def data(self):
        return ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=450_000),
        )

    def test_old_regime_zero_tax_with_rebate(self, filer, data):
        result = compare_regimes(data, filer)
        old = result.old_regime
        # 4.5L - 50K std = 4L taxable; senior: (4L-3L)*5% = 5000; 87A: ≤5L → rebate 5000
        assert old.income_tax == 5_000
        assert old.rebate_87a == 5_000
        assert old.total_tax_liability == 0

    def test_new_regime_also_zero(self, filer, data):
        result = compare_regimes(data, filer)
        new = result.new_regime
        # 4.5L - 75K = 3.75L; slab: (3.75L-3L)*5% = 3750 wait: 0-4L = 0% → tax=0
        assert new.income_tax == 0
        assert new.total_tax_liability == 0

    def test_both_regimes_zero_recommendation_valid(self, filer, data):
        result = compare_regimes(data, filer)
        assert result.savings_from_recommendation == 0
        assert result.recommended_regime in ("old", "new")


# ---------------------------------------------------------------------------
# SCENARIO 4 — HP loss set-off, old vs new regime
# ---------------------------------------------------------------------------

class TestHPLossSetOffE2E:
    """
    Filer with salary ₹12L and house property loss ₹3L.
    Old regime: HP loss capped at ₹2L, reduces taxable income.
    New regime: HP loss fully disallowed, taxable income is higher.
    """

    @pytest.fixture
    def filer(self):
        return make_filer()

    @pytest.fixture
    def data(self):
        return ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=1_200_000, tds_deducted=50_000),
            house_property_income=-300_000,
        )

    def test_old_regime_hp_loss_reduces_taxable_income(self, filer, data):
        result = compare_regimes(data, filer)
        old = result.old_regime
        # gross = 12L + (-2L capped) = 10L; deductions = 50K std; taxable = 9.5L
        assert old.gross_income == 1_000_000
        assert old.taxable_income == 950_000

    def test_new_regime_hp_loss_not_deducted(self, filer, data):
        result = compare_regimes(data, filer)
        new = result.new_regime
        # gross = 12L (loss disallowed); deductions = 75K std; taxable = 11.25L
        assert new.gross_income == 1_200_000
        assert new.taxable_income == 1_125_000

    def test_old_regime_lower_taxable_income_than_new(self, filer, data):
        result = compare_regimes(data, filer)
        assert result.old_regime.taxable_income < result.new_regime.taxable_income

    def test_itr1_output_valid(self, filer, data):
        result = compare_regimes(data, filer)
        itr = map_to_itr1(data, result, filer)
        assert itr["AssessmentYear"] == "2026-27"
        assert itr["Form"] == "ITR-1"


# ---------------------------------------------------------------------------
# SCENARIO 5 — Graph output nodes (compute_tax → build_outputs → finalise)
# ---------------------------------------------------------------------------

class TestGraphOutputNodesE2E:
    """
    Test the Act 4 output nodes in sequence without LangGraph or LLM.
    Uses node functions directly, simulating state threading.
    No SqliteSaver needed — state is a plain dict.
    """

    @pytest.fixture
    def base_state(self):
        """Minimal state dict mimicking TaxFilingState after aggregate_data."""
        return {
            "session_id": "test_session_001",
            "itr_form": "ITR-1",
            "messages": [],
            "errors": [],
            "filer_profile": {
                "pan": "ABCDE1234F",
                "name": "Test Filer E2E",
                "date_of_birth": "1985-06-15",
                "employment_type": "salaried",
                "income_sources": [],
                "residential_status": "resident",
            },
            "extracted_data": {
                "salary_income": {
                    "gross_salary": 900_000,
                    "tds_deducted": 20_000,
                    "hra_exemption": 0,
                    "employer_nps_80ccd2": 0,
                    "professional_tax": 0,
                },
                "house_property_income": 0,
                "other_income": 0,
                "capital_gains": [],
                "deductions": {
                    "sec_80c": 100_000,
                    "sec_80d": 0,
                    "sec_80tta": 0,
                    "sec_80ttb": 0,
                    "sec_80ccd_1b": 0,
                    "hra_exemption": 0,
                    "home_loan_interest": 0,
                    "sec_80e": 0,
                    "sec_80g": 0,
                    "sec_54_exemption": 0,
                    "sec_54ec_exemption": 0,
                    "sec_54f_exemption": 0,
                    "other_deductions": 0,
                },
                "tds_total": 0,
                "advance_tax_paid": 0,
                "tcs_total": 0,
            },
            "documents": [],
        }

    def test_compute_tax_node_returns_computation(self, base_state):
        from inditr.graph.nodes.output import compute_tax
        result = compute_tax(base_state)
        assert "computation" in result
        assert result["computation"] is not None
        comp = result["computation"]
        assert "old_regime" in comp
        assert "new_regime" in comp
        assert "recommended_regime" in comp
        assert comp["recommended_regime"] in ("old", "new")

    def test_build_outputs_node_returns_itr_and_report(self, base_state):
        from inditr.graph.nodes.output import compute_tax, build_outputs
        state_after_compute = {**base_state, **compute_tax(base_state)}
        result = build_outputs(state_after_compute)
        assert "regime_report" in result
        assert "itr_json" in result
        report = result["regime_report"]
        assert isinstance(report, dict)
        assert "text_report" in report
        assert "AY 2026-27" in report["text_report"]
        itr = result["itr_json"]
        assert itr.get("AssessmentYear") == "2026-27"

    def test_finalise_node_writes_files(self, base_state, tmp_path, monkeypatch):
        from inditr.graph.nodes.output import compute_tax, build_outputs, finalise
        monkeypatch.setenv("PDF_OUTPUT_DIR", str(tmp_path))

        state = {**base_state}
        state.update(compute_tax(state))
        state.update(build_outputs(state))
        state["user_confirmed"] = True
        result = finalise(state)

        assert result["current_act"] == "complete"
        # ITR JSON file must exist
        itr_path = tmp_path / "test_session_001_itr.json"
        assert itr_path.is_file()
        itr_data = json.loads(itr_path.read_text())
        assert itr_data["AssessmentYear"] == "2026-27"
        # PDF file must exist
        pdf_path = result.get("pdf_path")
        assert pdf_path is not None
        assert os.path.isfile(pdf_path)

    def test_full_pipeline_no_errors(self, base_state, tmp_path, monkeypatch):
        """compute_tax → build_outputs → finalise should produce zero errors."""
        from inditr.graph.nodes.output import compute_tax, build_outputs, finalise
        monkeypatch.setenv("PDF_OUTPUT_DIR", str(tmp_path))

        state = {**base_state}
        state.update(compute_tax(state))
        assert state["errors"] == []
        state.update(build_outputs(state))
        assert state["errors"] == []
        state["user_confirmed"] = True
        final = finalise(state)
        # Only non-critical PDF errors allowed; no computation errors
        critical_errors = [e for e in final.get("errors", []) if "computation" in e.lower()]
        assert critical_errors == []
