import pytest
from pydantic import ValidationError
from inditr.models.profile import FilerProfile, EmploymentType, IncomeSourceType, DocumentRequest


def make_valid_profile(**kwargs):
    defaults = dict(
        pan="ABCDE1234F",
        name="Test User",
        date_of_birth="1985-06-15",
        employment_type=EmploymentType.SALARIED,
    )
    defaults.update(kwargs)
    return FilerProfile(**defaults)


class TestFilerProfile:
    def test_valid_construction(self):
        p = make_valid_profile()
        assert p.pan == "ABCDE1234F"
        assert p.name == "Test User"

    def test_pan_uppercase_normalisation(self):
        p = make_valid_profile(pan="abcde1234f")
        assert p.pan == "ABCDE1234F"

    def test_pan_masked(self):
        p = make_valid_profile(pan="ABCDE1234F")
        assert p.masked_pan == "XXXXX1234X"

    def test_invalid_pan_short(self):
        with pytest.raises(ValidationError):
            make_valid_profile(pan="ABCD1234F")

    def test_invalid_pan_wrong_format(self):
        with pytest.raises(ValidationError):
            make_valid_profile(pan="12345ABCDE")

    def test_invalid_pan_lowercase_not_normalised_when_invalid(self):
        with pytest.raises(ValidationError):
            make_valid_profile(pan="ABCDE123FF")  # 3 alpha at end

    def test_income_sources_default_empty(self):
        p = make_valid_profile()
        assert p.income_sources == []

    def test_income_sources_set(self):
        p = make_valid_profile(income_sources=[IncomeSourceType.SALARY, IncomeSourceType.CAPITAL_GAINS])
        assert IncomeSourceType.SALARY in p.income_sources


class TestDocumentRequest:
    def test_valid(self):
        dr = DocumentRequest(doc_type="form_16", description="Salary TDS certificate")
        assert dr.mandatory is True

    def test_optional_document(self):
        dr = DocumentRequest(doc_type="form_26as", description="Tax credit statement", mandatory=False)
        assert dr.mandatory is False
