import pytest
from pydantic import ValidationError
from inditr.models.outputs import Clarification, CrossCheckResult, FilingOutputs


class TestClarification:
    def test_valid(self):
        c = Clarification(field_name="gross_salary", question="What is your gross salary?")
        assert c.answer is None

    def test_with_answer(self):
        c = Clarification(field_name="gross_salary", question="What is your gross salary?", answer="700000")
        assert c.answer == "700000"


class TestCrossCheckResult:
    def test_pass(self):
        r = CrossCheckResult(check="salary_vs_bank", passed=True, severity="pass", message="OK")
        assert r.passed is True

    def test_critical(self):
        r = CrossCheckResult(
            check="salary_vs_bank",
            passed=False,
            severity="critical",
            message="Salary mismatch exceeds 2% tolerance",
        )
        assert r.severity == "critical"

    def test_invalid_severity(self):
        with pytest.raises(ValidationError):
            CrossCheckResult(check="x", passed=False, severity="error", message="x")


class TestFilingOutputs:
    def test_defaults(self):
        fo = FilingOutputs()
        assert fo.itr_json_path is None
        assert "IndITR" in fo.disclaimer
        assert "Chartered Accountant" in fo.disclaimer
