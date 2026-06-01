"""
Tests for Form16Parser.
Tests use synthetic PDFs created with reportlab since real Form 16 PDFs are not available.
"""
import pytest
from inditr.models.documents import ParsedDocument
from inditr.parsers.form16 import Form16Parser


def create_synthetic_form16_pdf(path: str) -> None:
    """Create a minimal synthetic Form 16 PDF for testing."""
    try:
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(path)
        c.drawString(100, 800, "FORM NO. 16")
        c.drawString(100, 780, "Certificate under section 203 of the Income Tax Act, 1961")
        c.drawString(100, 760, "TAN of Employer: ABCD01234E")
        c.drawString(100, 740, "PAN of Employee: ABCDE1234F")
        c.drawString(100, 720, "Name of Employer: Test Company Pvt Ltd")
        c.drawString(100, 700, "PART B - Details of Salary paid and Tax deducted")
        c.drawString(100, 680, "1. Gross Salary: 700000")
        c.drawString(100, 660, "2. Standard Deduction u/s 16(ia): 50000")
        c.drawString(100, 640, "3. Income chargeable under the head Salaries: 650000")
        c.drawString(100, 620, "4. Total Tax Deducted at Source: 30000")
        c.drawString(100, 600, "5. Deduction u/s 80C: 150000")
        c.showPage()
        c.save()
    except ImportError:
        # If reportlab not available, create a minimal valid PDF manually
        pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]
/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 200 >>
stream
BT
/F1 12 Tf
100 800 Td (FORM NO. 16) Tj
0 -20 Td (TAN of Employer: ABCD01234E) Tj
0 -20 Td (PAN of Employee: ABCDE1234F) Tj
0 -20 Td (Gross Salary: 700000) Tj
0 -20 Td (Standard Deduction u/s 16(ia): 50000) Tj
0 -20 Td (Total Tax Deducted at Source: 30000) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000274 00000 n
0000000528 00000 n
trailer
<< /Size 6 /Root 1 0 R >>
startxref
614
%%EOF"""
        with open(path, "wb") as f:
            f.write(pdf_content)


class TestForm16Parser:
    def test_can_parse_returns_false_for_csv(self):
        parser = Form16Parser()
        assert parser.can_parse("some_file.csv") is False

    def test_can_parse_returns_false_for_txt(self):
        parser = Form16Parser()
        assert parser.can_parse("document.txt") is False

    def test_parse_nonexistent_returns_parseddocument_with_errors(self):
        parser = Form16Parser()
        doc = parser.parse("/nonexistent/form16.pdf")
        assert isinstance(doc, ParsedDocument)
        assert len(doc.parse_errors) > 0
        assert doc.doc_type == "form_16"

    def test_parse_never_raises(self):
        """Verify parse() never raises even for garbage input."""
        parser = Form16Parser()
        for bad_path in [
            "/nonexistent.pdf",
            "",
            "not_a_path",
        ]:
            try:
                result = parser.parse(bad_path)
                assert isinstance(result, ParsedDocument)
            except Exception as e:
                pytest.fail(f"parse() raised {e!r} for path {bad_path!r}")

    def test_parse_synthetic_form16(self, tmp_path):
        """Test parsing a synthetic Form 16 PDF."""
        pdf_path = str(tmp_path / "form16.pdf")
        create_synthetic_form16_pdf(pdf_path)

        parser = Form16Parser()
        doc = parser.parse(pdf_path)
        assert isinstance(doc, ParsedDocument)
        assert doc.doc_type == "form_16"
        # With synthetic PDF containing Form 16 content
        # Some fields may be extracted, others may produce parse_errors
        # The key assertion is that it returns a valid ParsedDocument

    def test_parse_result_has_valid_confidence_scores(self, tmp_path):
        """All confidence scores must be between 0.0 and 1.0."""
        pdf_path = str(tmp_path / "form16.pdf")
        create_synthetic_form16_pdf(pdf_path)
        parser = Form16Parser()
        doc = parser.parse(pdf_path)
        for field_name, field in doc.fields.items():
            assert 0.0 <= field.confidence <= 1.0, (
                f"Field {field_name!r} has invalid confidence {field.confidence}"
            )

    def test_low_confidence_fields_trigger_requires_review(self, tmp_path):
        """Fields with confidence < 0.85 must have requires_review=True."""
        pdf_path = str(tmp_path / "form16.pdf")
        create_synthetic_form16_pdf(pdf_path)
        parser = Form16Parser()
        doc = parser.parse(pdf_path)
        for field_name, field in doc.fields.items():
            if field.confidence < 0.85:
                assert field.requires_review is True, (
                    f"Field {field_name!r} with confidence {field.confidence} must have requires_review=True"
                )

    def test_overall_confidence_is_float_in_range(self, tmp_path):
        """overall_confidence must be a float in [0.0, 1.0]."""
        pdf_path = str(tmp_path / "form16.pdf")
        create_synthetic_form16_pdf(pdf_path)
        parser = Form16Parser()
        doc = parser.parse(pdf_path)
        assert isinstance(doc.overall_confidence, float)
        assert 0.0 <= doc.overall_confidence <= 1.0
