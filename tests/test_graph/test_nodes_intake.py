"""
Tests for Act 1 intake nodes — pure Python nodes only (no LLM mock needed for deterministic nodes).
"""
import pytest
from inditr.graph.nodes.intake import determine_itr_form, build_doc_checklist


class TestDetermineItrForm:
    """determine_itr_form is pure Python — test directly."""

    def test_salary_only_gives_itr1(self):
        state = {
            "filer_profile": {"income_sources": ["salary"]},
            "errors": [],
        }
        result = determine_itr_form(state)
        assert result["itr_form"] == "ITR-1"

    def test_capital_gains_gives_itr2(self):
        state = {
            "filer_profile": {"income_sources": ["salary", "capital_gains"]},
            "errors": [],
        }
        result = determine_itr_form(state)
        assert result["itr_form"] == "ITR-2"

    def test_house_property_gives_itr1(self):
        # AY 2026-27: ITR-1 supports up to 2 house properties; HP alone no longer forces ITR-2
        state = {
            "filer_profile": {"income_sources": ["salary", "house_property"]},
            "errors": [],
        }
        result = determine_itr_form(state)
        assert result["itr_form"] == "ITR-1"

    def test_house_property_with_capital_gains_gives_itr2(self):
        state = {
            "filer_profile": {"income_sources": ["salary", "house_property", "capital_gains"]},
            "errors": [],
        }
        result = determine_itr_form(state)
        assert result["itr_form"] == "ITR-2"

    def test_empty_sources_defaults_itr1(self):
        state = {
            "filer_profile": {"income_sources": []},
            "errors": [],
        }
        result = determine_itr_form(state)
        assert result["itr_form"] == "ITR-1"

    def test_returns_current_act(self):
        state = {"filer_profile": {"income_sources": ["salary"]}, "errors": []}
        result = determine_itr_form(state)
        assert "current_act" in result


class TestBuildDocChecklist:
    def test_itr1_has_form16(self):
        state = {
            "itr_form": "ITR-1",
            "filer_profile": {"income_sources": ["salary"]},
            "errors": [],
        }
        result = build_doc_checklist(state)
        checklist = result["document_checklist"]
        doc_types = [d["doc_type"] for d in checklist]
        assert "form_16" in doc_types

    def test_itr2_has_capital_gains_statement(self):
        state = {
            "itr_form": "ITR-2",
            "filer_profile": {"income_sources": ["salary", "capital_gains"]},
            "errors": [],
        }
        result = build_doc_checklist(state)
        checklist = result["document_checklist"]
        doc_types = [d["doc_type"] for d in checklist]
        assert "capital_gains_statement" in doc_types

    def test_salary_income_adds_bank_statement(self):
        state = {
            "itr_form": "ITR-1",
            "filer_profile": {"income_sources": ["salary"]},
            "errors": [],
        }
        result = build_doc_checklist(state)
        doc_types = [d["doc_type"] for d in result["document_checklist"]]
        assert "bank_statement" in doc_types

    def test_checklist_items_have_required_keys(self):
        state = {
            "itr_form": "ITR-1",
            "filer_profile": {"income_sources": ["salary"]},
            "errors": [],
        }
        result = build_doc_checklist(state)
        for item in result["document_checklist"]:
            assert "doc_type" in item
            assert "description" in item
            assert "mandatory" in item

    def test_returns_errors_list(self):
        state = {
            "itr_form": "ITR-1",
            "filer_profile": {"income_sources": []},
            "errors": [],
        }
        result = build_doc_checklist(state)
        assert isinstance(result["errors"], list)
