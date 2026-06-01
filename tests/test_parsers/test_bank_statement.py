"""Tests for BankStatementParser — LLM-based architecture."""
import pytest
from inditr.models.documents import ParsedDocument
from inditr.parsers.bank_statement import BankStatementParser, _BANK_NAME_RE, _ID_KEYWORDS


class TestBankIdentification:
    """Identification is now regex-based on the full text, not a standalone function."""

    def test_bank_name_re_matches_hdfc(self):
        assert _BANK_NAME_RE.search("HDFC Bank Account Statement")

    def test_bank_name_re_matches_sbi(self):
        assert _BANK_NAME_RE.search("State Bank of India - Account Statement")

    def test_bank_name_re_matches_icici(self):
        assert _BANK_NAME_RE.search("ICICI Bank Ltd. Statement of Account")

    def test_bank_name_re_matches_canara(self):
        assert _BANK_NAME_RE.search("Canara Bank e-Passbook")

    def test_bank_name_re_no_false_positive(self):
        # UPI description like "SU/HDFC/**NE628@OKHDFCBANK" should NOT trigger
        # when evaluated against 200-char header — but the regex alone doesn't
        # enforce the 200-char limit; can_parse() does.
        assert not _BANK_NAME_RE.search("Some Random Financial Corp XYZ")

    def test_id_keywords_present(self):
        assert "statement for a/c" in _ID_KEYWORDS
        assert "passbook" in _ID_KEYWORDS


class TestBankStatementParser:
    def test_parse_nonexistent_returns_parse_errors(self):
        parser = BankStatementParser()
        doc = parser.parse("/nonexistent/statement.pdf")
        assert isinstance(doc, ParsedDocument)
        assert len(doc.parse_errors) > 0

    def test_parse_never_raises(self):
        parser = BankStatementParser()
        for bad_path in ["/nonexistent.pdf", "", "garbage"]:
            try:
                result = parser.parse(bad_path)
                assert isinstance(result, ParsedDocument)
            except Exception as e:
                pytest.fail(f"parse() raised {e!r}")

    def test_can_parse_returns_false_for_csv(self):
        parser = BankStatementParser()
        assert parser.can_parse("statement.csv") is False

    def test_can_parse_returns_false_for_non_pdf(self):
        parser = BankStatementParser()
        assert parser.can_parse("D:/taxagn/pyproject.toml") is False

    def test_confidence_between_0_and_1(self):
        """Even for failed parses, any confidence values must be in range."""
        parser = BankStatementParser()
        doc = parser.parse("/nonexistent.pdf")
        for field in doc.fields.values():
            assert 0.0 <= field.confidence <= 1.0
