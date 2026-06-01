"""
Tests for Act 2 document nodes — pure Python nodes only.
"""
import pytest
from inditr.graph.nodes.documents import validate_extractions


class TestValidateExtractions:
    def test_high_confidence_no_low_conf_fields(self):
        state = {
            "documents": [
                {
                    "doc_id": "abc",
                    "doc_type": "form_16",
                    "fields": {
                        "gross_salary": {"confidence": 0.95, "value": 700000},
                        "total_tds": {"confidence": 0.95, "value": 30000},
                    },
                }
            ],
            "errors": [],
        }
        result = validate_extractions(state)
        assert result["low_confidence_fields"] == []

    def test_low_confidence_field_flagged(self):
        state = {
            "documents": [
                {
                    "doc_id": "abc",
                    "doc_type": "form_16",
                    "fields": {
                        "gross_salary": {"confidence": 0.95, "value": 700000},
                        "employer_name": {"confidence": 0.70, "value": "Test Co"},
                    },
                }
            ],
            "errors": [],
        }
        result = validate_extractions(state)
        assert len(result["low_confidence_fields"]) == 1
        assert "employer_name" in result["low_confidence_fields"][0]

    def test_exactly_085_not_flagged(self):
        state = {
            "documents": [
                {
                    "doc_id": "abc",
                    "doc_type": "form_16",
                    "fields": {
                        "gross_salary": {"confidence": 0.85, "value": 700000},
                    },
                }
            ],
            "errors": [],
        }
        result = validate_extractions(state)
        assert result["low_confidence_fields"] == []

    def test_empty_documents_no_errors(self):
        state = {"documents": [], "errors": []}
        result = validate_extractions(state)
        assert result["low_confidence_fields"] == []
        assert result["errors"] == []

    def test_multiple_docs_multiple_low_conf(self):
        state = {
            "documents": [
                {
                    "doc_type": "form_16",
                    "fields": {"gross_salary": {"confidence": 0.60, "value": None}},
                },
                {
                    "doc_type": "bank_statement",
                    "fields": {"salary_credits": {"confidence": 0.50, "value": []}},
                },
            ],
            "errors": [],
        }
        result = validate_extractions(state)
        assert len(result["low_confidence_fields"]) == 2
