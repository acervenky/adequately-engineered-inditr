"""
Tests for conditional edge routing functions.
"""
import pytest
from inditr.graph.edges import (
    route_after_validation,
    route_after_cross_check,
    route_after_final_review,
)


class TestRouteAfterValidation:
    def test_no_low_conf_routes_to_gap_fill(self):
        state = {"low_confidence_fields": []}
        assert route_after_validation(state) == "gap_fill_chat"

    def test_low_conf_routes_to_human_review(self):
        state = {"low_confidence_fields": ["form_16/gross_salary (confidence=0.70)"]}
        assert route_after_validation(state) == "human_doc_review"

    def test_missing_field_defaults_to_gap_fill(self):
        state = {}
        assert route_after_validation(state) == "gap_fill_chat"


class TestRouteAfterCrossCheck:
    def test_no_critical_routes_to_aggregate(self):
        state = {
            "cross_check_results": [
                {"check": "salary_check", "passed": True, "severity": "pass", "message": "OK"},
            ]
        }
        assert route_after_cross_check(state) == "aggregate_data"

    def test_critical_failure_routes_to_gap_fill(self):
        state = {
            "cross_check_results": [
                {"check": "salary_check", "passed": False, "severity": "critical", "message": "Mismatch"},
            ]
        }
        assert route_after_cross_check(state) == "gap_fill_chat"

    def test_warning_routes_to_aggregate(self):
        state = {
            "cross_check_results": [
                {"check": "salary_check", "passed": False, "severity": "warning", "message": "Minor diff"},
            ]
        }
        assert route_after_cross_check(state) == "aggregate_data"

    def test_empty_results_routes_to_aggregate(self):
        state = {"cross_check_results": []}
        assert route_after_cross_check(state) == "aggregate_data"


class TestRouteAfterFinalReview:
    def test_confirmed_routes_to_finalise(self):
        state = {"user_confirmed": True}
        assert route_after_final_review(state) == "finalise"

    def test_not_confirmed_routes_to_aggregate(self):
        state = {"user_confirmed": False}
        assert route_after_final_review(state) == "aggregate_data"

    def test_missing_confirmed_routes_to_aggregate(self):
        state = {}
        assert route_after_final_review(state) == "aggregate_data"
