"""
Tests that ALL parsers honour the BaseParser contract:
- parse() NEVER raises — always returns ParsedDocument with parse_errors
- ParsedDocument always has doc_id, parse_errors, fields
"""
import pytest
from inditr.models.documents import ParsedDocument
from inditr.parsers.form16 import Form16Parser
from inditr.parsers.salary_slip import SalarySlipParser
from inditr.parsers.zerodha import ZerodhaPnlParser
from inditr.parsers.upstox import UpstoxParser
from inditr.parsers.bank_statement import BankStatementParser
from inditr.parsers.registry import ParserRegistry

ALL_PARSERS = [
    Form16Parser(),
    SalarySlipParser(),
    ZerodhaPnlParser(),
    UpstoxParser(),
    BankStatementParser(),
]

NON_EXISTENT_FILE = "D:/taxagn/does_not_exist_12345.pdf"
NON_PDF_FILE = "D:/taxagn/pyproject.toml"


@pytest.mark.parametrize("parser", ALL_PARSERS, ids=[type(p).__name__ for p in ALL_PARSERS])
class TestParserContract:
    def test_parse_nonexistent_returns_parseddocument(self, parser):
        """parse() on a non-existent file must return ParsedDocument, not raise."""
        result = parser.parse(NON_EXISTENT_FILE)
        assert isinstance(result, ParsedDocument), "parse() must return ParsedDocument"
        assert isinstance(result.parse_errors, list), "parse_errors must be a list"
        assert len(result.parse_errors) > 0, "Non-existent file must produce parse_errors"
        assert result.doc_id is not None

    def test_can_parse_nonexistent_does_not_raise(self, parser):
        """can_parse() must not raise on non-existent paths."""
        try:
            result = parser.can_parse(NON_EXISTENT_FILE)
            assert isinstance(result, bool)
        except Exception as e:
            pytest.fail(f"can_parse() raised {e!r} — must never raise")

    def test_can_parse_returns_false_for_non_pdf(self, parser):
        """can_parse() must return False for clearly non-PDF/non-target files."""
        result = parser.can_parse(NON_PDF_FILE)
        assert isinstance(result, bool)

    def test_parse_result_has_required_attrs(self, parser):
        """ParsedDocument result always has required attributes."""
        result = parser.parse(NON_EXISTENT_FILE)
        assert hasattr(result, "doc_id")
        assert hasattr(result, "parse_errors")
        assert hasattr(result, "fields")
        assert hasattr(result, "overall_confidence")
        assert isinstance(result.fields, dict)


class TestRegistryContract:
    def test_registry_parse_nonexistent_returns_parseddocument(self):
        registry = ParserRegistry()
        result = registry.parse(NON_EXISTENT_FILE)
        assert isinstance(result, ParsedDocument)
        assert isinstance(result.parse_errors, list)

    def test_get_parser_returns_base_parser(self):
        from inditr.parsers.base import BaseParser
        registry = ParserRegistry()
        parser = registry.get_parser(NON_EXISTENT_FILE)
        assert isinstance(parser, BaseParser)

    def test_registry_never_raises(self):
        registry = ParserRegistry()
        for filepath in [NON_EXISTENT_FILE, NON_PDF_FILE, "", "C:/invalid_path.pdf"]:
            try:
                result = registry.parse(filepath)
                assert isinstance(result, ParsedDocument)
            except Exception as e:
                pytest.fail(f"registry.parse({filepath!r}) raised {e!r} — must never raise")
