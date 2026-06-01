import pytest
from pydantic import ValidationError
from inditr.models.documents import ExtractedField, ParsedDocument


class TestExtractedField:
    def test_valid_high_confidence(self):
        f = ExtractedField(value=100000, source_document="form16.pdf", confidence=0.95)
        assert f.requires_review is False

    def test_low_confidence_sets_requires_review(self):
        f = ExtractedField(value=100000, source_document="form16.pdf", confidence=0.80)
        assert f.requires_review is True

    def test_exactly_0_85_does_not_require_review(self):
        f = ExtractedField(value=100000, source_document="form16.pdf", confidence=0.85)
        assert f.requires_review is False

    def test_confidence_above_1_raises(self):
        with pytest.raises(ValidationError):
            ExtractedField(value=100000, source_document="form16.pdf", confidence=1.1)

    def test_confidence_below_0_raises(self):
        with pytest.raises(ValidationError):
            ExtractedField(value=100000, source_document="form16.pdf", confidence=-0.1)


class TestParsedDocument:
    def test_valid_construction(self):
        doc = ParsedDocument(doc_type="form_16", filename="form16.pdf")
        assert doc.doc_id is not None
        assert doc.parse_errors == []
        assert doc.overall_confidence == 1.0

    def test_overall_confidence_min_of_fields(self):
        doc = ParsedDocument(
            doc_type="form_16",
            filename="form16.pdf",
            fields={
                "gross_salary": ExtractedField(value=500000, source_document="form16.pdf", confidence=0.95),
                "tds": ExtractedField(value=20000, source_document="form16.pdf", confidence=0.70),
            },
        )
        assert doc.overall_confidence == pytest.approx(0.70)

    def test_parse_errors_stored(self):
        doc = ParsedDocument(
            doc_type="form_16",
            filename="form16.pdf",
            parse_errors=["Could not extract employer PAN"],
        )
        assert len(doc.parse_errors) == 1

    def test_unique_doc_ids(self):
        d1 = ParsedDocument(doc_type="form_16", filename="a.pdf")
        d2 = ParsedDocument(doc_type="form_16", filename="b.pdf")
        assert d1.doc_id != d2.doc_id
