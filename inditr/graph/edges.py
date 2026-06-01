"""
Conditional edge functions for the LangGraph graph.
These are pure Python functions — no LLM calls.
"""
from __future__ import annotations
from typing import Literal

from inditr.models.state import TaxFilingState


def route_after_validation(state: TaxFilingState) -> Literal["human_doc_review", "gap_fill_chat"]:
    """
    If there are low-confidence fields -> human_doc_review
    Otherwise -> gap_fill_chat
    """
    low_conf = state.get("low_confidence_fields", [])
    if low_conf:
        return "human_doc_review"
    return "gap_fill_chat"


def route_after_cross_check(state: TaxFilingState) -> Literal["gap_fill_chat", "aggregate_data"]:
    """
    If there are critical cross-check failures -> gap_fill_chat (for correction)
    Otherwise -> aggregate_data
    """
    results = state.get("cross_check_results", [])
    has_critical = any(r.get("severity") == "critical" for r in results)
    if has_critical:
        return "gap_fill_chat"
    return "aggregate_data"


def route_after_advisor(state: TaxFilingState) -> Literal["tax_advisor", "human_final_review"]:
    """
    If advisor set current_act to human_final_review (user ready to file) -> human_final_review
    Otherwise -> tax_advisor (continue conversation)
    """
    if state.get("current_act") == "human_final_review":
        return "human_final_review"
    return "tax_advisor"


def route_after_final_review(state: TaxFilingState) -> Literal["finalise", "aggregate_data"]:
    """
    If user confirmed -> finalise
    Otherwise -> aggregate_data (for revision)
    """
    if state.get("user_confirmed"):
        return "finalise"
    return "aggregate_data"
