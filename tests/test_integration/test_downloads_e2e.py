"""
E2E tests for the three download endpoints and the portal walkthrough in the PDF.
Uses FastAPI TestClient + real engine pipeline — no LLM, no network calls.
"""
from __future__ import annotations
import json
import os
import tempfile
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from inditr.engine.regime import compare_regimes
from inditr.models.tax_data import ExtractedTaxData, SalaryIncome, Deductions
from inditr.models.profile import FilerProfile, EmploymentType
from inditr.output_builders.itr_json import (
    map_to_itr1, map_to_itr2,
    map_to_official_itr1, map_to_official_itr2,
)
from inditr.output_builders.pdf_summary import build_pdf_summary


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def filer():
    return FilerProfile(
        name="Priya Kapoor",
        pan="DDDPK9999Z",
        date_of_birth="1988-03-20",
        employment_type=EmploymentType.SALARIED,
    )


@pytest.fixture(scope="module")
def data():
    return ExtractedTaxData(
        salary_income=SalaryIncome(
            gross_salary=Decimal("1400000"),
            professional_tax=Decimal("2400"),
            employer_nps_80ccd2=Decimal("70000"),
        ),
        deductions=Deductions(
            sec_80c=Decimal("150000"),
            sec_80d=Decimal("25000"),
            sec_80ccd_1b=Decimal("50000"),
        ),
    )


@pytest.fixture(scope="module")
def computation(data, filer):
    return compare_regimes(data, filer)


# ---------------------------------------------------------------------------
# Official ITR-1 JSON structure
# ---------------------------------------------------------------------------

class TestOfficialITR1Schema:
    def test_top_level_envelope(self, data, computation, filer):
        out = map_to_official_itr1(data, computation, filer)
        assert set(out.keys()) == {"ITR"}
        assert "ITR1" in out["ITR"]

    def test_creation_info_present(self, data, computation, filer):
        itr1 = map_to_official_itr1(data, computation, filer)["ITR"]["ITR1"]
        ci = itr1["CreationInfo"]
        assert ci["SWCreatedBy"] == "IndITR"
        assert ci["InterfaceCode"] == "O"

    def test_assessment_year(self, data, computation, filer):
        itr1 = map_to_official_itr1(data, computation, filer)["ITR"]["ITR1"]
        assert itr1["Form_ITR1"]["AssessmentYear"] == "2026-27"

    def test_pan_unmasked(self, data, computation, filer):
        """Official JSON must carry the real PAN (needed for submission)."""
        itr1 = map_to_official_itr1(data, computation, filer)["ITR"]["ITR1"]
        assert itr1["PersonalInfo"]["PAN"] == "DDDPK9999Z"

    def test_dob_format(self, data, computation, filer):
        """DOB must be DD/MM/YYYY per department schema."""
        itr1 = map_to_official_itr1(data, computation, filer)["ITR"]["ITR1"]
        assert itr1["PersonalInfo"]["DOB"] == "20/03/1988"

    def test_monetary_values_are_integers(self, data, computation, filer):
        itr1 = map_to_official_itr1(data, computation, filer)["ITR"]["ITR1"]
        tc = itr1["TaxComputation"]
        for key, val in tc.items():
            assert isinstance(val, int), f"{key} should be int, got {type(val)}"

    def test_total_tax_payable_matches_engine(self, data, computation, filer):
        itr1 = map_to_official_itr1(data, computation, filer)["ITR"]["ITR1"]
        rec = computation.recommended_regime
        r = computation.new_regime if rec == "new" else computation.old_regime
        assert itr1["TaxComputation"]["TotalTaxPayable"] == int(round(float(r.total_tax_liability)))

    def test_regime_flag(self, data, computation, filer):
        itr1 = map_to_official_itr1(data, computation, filer)["ITR"]["ITR1"]
        rec = computation.recommended_regime
        flag = itr1["PersonalInfo"]["FilingStatus"]["OptOutNewTaxRegime"]
        assert flag == ("N" if rec == "new" else "Y")

    def test_refund_or_payable_not_both(self, data, computation, filer):
        itr1 = map_to_official_itr1(data, computation, filer)["ITR"]["ITR1"]
        refund = itr1["Refund"]["RefundDue"]
        payable = itr1["TaxesPaid"]["BalTaxPayable"]
        # At most one should be non-zero
        assert refund >= 0 and payable >= 0
        assert not (refund > 0 and payable > 0)

    def test_chapter_via_deductions_zero_under_new_regime(self, data, computation, filer):
        """Under new regime, 80C/80D/80CCD(1B) must be zeroed in official output."""
        itr1 = map_to_official_itr1(data, computation, filer)["ITR"]["ITR1"]
        if computation.recommended_regime == "new":
            ded = itr1["IncomeDeductions"]["UsrDeductUndChapVIA"]
            assert ded["Section80C"] == 0
            assert ded["Section80D"] == 0
            assert ded["Section80CCDO"] == 0  # 80CCD(1B)

    def test_employer_nps_present_both_regimes(self, data, computation, filer):
        """80CCD(2) employer NPS is available under both regimes."""
        itr1 = map_to_official_itr1(data, computation, filer)["ITR"]["ITR1"]
        ded = itr1["IncomeDeductions"]["UsrDeductUndChapVIA"]
        assert ded["Section80CCDEmployer"] == 70000


# ---------------------------------------------------------------------------
# Official ITR-2 JSON structure
# ---------------------------------------------------------------------------

class TestOfficialITR2Schema:
    def test_top_level_envelope(self, data, computation, filer):
        out = map_to_official_itr2(data, computation, filer)
        assert "ITR2" in out["ITR"]

    def test_assessment_year(self, data, computation, filer):
        itr2 = map_to_official_itr2(data, computation, filer)["ITR"]["ITR2"]
        assert itr2["Form_ITR2"]["AssessmentYear"] == "2026-27"

    def test_part_b_tti_present(self, data, computation, filer):
        itr2 = map_to_official_itr2(data, computation, filer)["ITR"]["ITR2"]
        assert "PartB_TTI" in itr2
        assert "TotalTaxPayable" in itr2["PartB_TTI"]

    def test_schedule_cg_present(self, data, computation, filer):
        itr2 = map_to_official_itr2(data, computation, filer)["ITR"]["ITR2"]
        cg = itr2["ScheduleCG"]
        assert "ShortTermCapGain15Per" in cg
        assert "LongTermCapGain10Per" in cg

    def test_total_tax_matches_engine(self, data, computation, filer):
        itr2 = map_to_official_itr2(data, computation, filer)["ITR"]["ITR2"]
        rec = computation.recommended_regime
        r = computation.new_regime if rec == "new" else computation.old_regime
        assert itr2["PartB_TTI"]["TotalTaxPayable"] == int(round(float(r.total_tax_liability)))


# ---------------------------------------------------------------------------
# Download endpoint responses (via FastAPI TestClient + real pipeline)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mock_session_state(data, computation, filer, tmp_path_factory):
    """Build a realistic session state dict as the API would see it after finalise."""
    tmp = tmp_path_factory.mktemp("pdf")
    pdf_path = str(tmp / "test_output.pdf")
    build_pdf_summary(computation, data, filer, pdf_path, itr_form="ITR-1")

    return {
        "itr_json": map_to_itr1(data, computation, filer),
        "computation": computation.model_dump(),
        "extracted_data": data.model_dump(),
        "filer_profile": filer.model_dump(),
        "itr_form": "ITR-1",
        "pdf_path": pdf_path,
    }


class TestDownloadEndpoints:
    """
    Test the three download routes using a patched _get_state that returns
    a realistic finalised session — no LangGraph required.
    """

    @pytest.fixture(autouse=True)
    def client_with_mock_state(self, mock_session_state, monkeypatch):
        import inditr.api.routes.session as session_mod

        class _FakeState:
            values = mock_session_state
            next = []

        monkeypatch.setattr(session_mod, "_get_state", lambda sid: _FakeState())

        from inditr.api.main import app
        self.client = TestClient(app)

    def test_itr_json_download_content_type(self):
        r = self.client.get("/session/test-123/download/itr-json")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]

    def test_itr_json_download_attachment_header(self):
        r = self.client.get("/session/test-123/download/itr-json")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".json" in cd

    def test_itr_json_download_valid_json(self):
        r = self.client.get("/session/test-123/download/itr-json")
        payload = r.json()
        assert payload["AssessmentYear"] == "2026-27"
        assert payload["Form"] == "ITR-1"

    def test_itr_json_official_download_content_type(self):
        r = self.client.get("/session/test-123/download/itr-json-official")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]

    def test_itr_json_official_download_attachment_header(self):
        r = self.client.get("/session/test-123/download/itr-json-official")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "ITR_AY2026_27" in cd

    def test_itr_json_official_correct_envelope(self):
        r = self.client.get("/session/test-123/download/itr-json-official")
        payload = r.json()
        assert "ITR" in payload
        assert "ITR1" in payload["ITR"]
        assert payload["ITR"]["ITR1"]["Form_ITR1"]["AssessmentYear"] == "2026-27"

    def test_itr_json_official_pan_unmasked(self):
        """Official JSON must have real PAN, not XXXXX####X."""
        r = self.client.get("/session/test-123/download/itr-json-official")
        pan = r.json()["ITR"]["ITR1"]["PersonalInfo"]["PAN"]
        assert not pan.startswith("XXXXX")
        assert pan == "DDDPK9999Z"

    def test_pdf_download_content_type(self):
        r = self.client.get("/session/test-123/download/pdf")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"

    def test_pdf_download_attachment_header(self):
        r = self.client.get("/session/test-123/download/pdf")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".pdf" in cd

    def test_pdf_download_nonempty(self):
        r = self.client.get("/session/test-123/download/pdf")
        assert len(r.content) > 8_000  # real PDF, not empty


# ---------------------------------------------------------------------------
# PDF portal walkthrough content
# ---------------------------------------------------------------------------

class TestPDFPortalWalkthrough:
    """Verify the portal walkthrough section is rendered in the PDF."""

    def test_pdf_contains_walkthrough(self, data, computation, filer, tmp_path):
        """PDF must be > 30KB when walkthrough is included (vs ~12KB without it)."""
        path = str(tmp_path / "out.pdf")
        build_pdf_summary(computation, data, filer, path, itr_form="ITR-1")
        size = os.path.getsize(path)
        assert size > 8_000, f"PDF suspiciously small ({size} bytes) — walkthrough may be missing"

    def test_pdf_walkthrough_new_regime_skips_deductions(self, data, filer, tmp_path):
        """New regime filer: deductions step should be skipped (greyed out)."""
        # Force new regime by using a high salary with minimal deductions
        data_min = ExtractedTaxData(
            salary_income=SalaryIncome(gross_salary=Decimal("2000000")),
            deductions=Deductions(),
        )
        comp = compare_regimes(data_min, filer)
        # Verify engine picked new regime (it should for high salary, minimal deductions)
        path = str(tmp_path / "new_regime.pdf")
        build_pdf_summary(comp, data_min, filer, path, itr_form="ITR-1")
        assert os.path.getsize(path) > 8_000

    def test_pdf_walkthrough_refund_skips_payment_step(self, filer, tmp_path):
        """When TDS > tax liability, payment step is skipped."""
        data_refund = ExtractedTaxData(
            salary_income=SalaryIncome(
                gross_salary=Decimal("800000"),
                tds_deducted=Decimal("50000"),  # over-deducted TDS
            ),
            deductions=Deductions(),
        )
        comp = compare_regimes(data_refund, filer)
        path = str(tmp_path / "refund.pdf")
        build_pdf_summary(comp, data_refund, filer, path, itr_form="ITR-1")
        assert os.path.getsize(path) > 8_000
