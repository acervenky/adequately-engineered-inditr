"""
LangGraph graph assembly for IndITR.
Entry:        collect_profile
Checkpointer: SqliteSaver (thread_id == session_id)

Interrupt strategy
──────────────────
interrupt_before=["human_doc_review", "human_final_review"]
  Graph pauses before these nodes. The API reads relevant state fields
  (low_confidence_fields / computation) to show the user what needs review,
  then injects corrections/confirmation via graph.update_state() before resuming.
  The nodes themselves are simple — they just process what's already in state.

interrupt_after=["tax_advisor"]
  Advisor runs first (proactive opening message after computation), then the graph
  pauses. User replies → API adds message to state → resume → advisor runs again.
  This creates the natural back-and-forth conversation loop.

Runtime
───────
build_graph() is called once at startup by session.py via get_graph() (@lru_cache).
All session state is persisted to SQLite by SqliteSaver after every node execution.
"""
from __future__ import annotations

from langgraph.graph import StateGraph, END

from inditr.models.state import TaxFilingState
from inditr.graph.nodes.intake import (
    collect_profile, identify_income_sources,
    determine_itr_form, build_doc_checklist,
)
from inditr.graph.nodes.documents import (
    request_documents, parse_documents,
    validate_extractions, human_doc_review,
)
from inditr.graph.nodes.gap_fill import gap_fill_chat, cross_check, aggregate_data
from inditr.graph.nodes.output import compute_tax, build_outputs, human_final_review, finalise
from inditr.graph.nodes.advisor import tax_advisor
from inditr.graph.edges import (
    route_after_validation,
    route_after_cross_check,
    route_after_final_review,
    route_after_advisor,
)


def build_graph(use_checkpointer: bool = True):
    """
    Build and compile the IndITR LangGraph agent.

    Args:
        use_checkpointer: If True, attach SqliteSaver. Set False for testing.

    Returns:
        CompiledGraph
    """
    builder = StateGraph(TaxFilingState)

    # --- Add all nodes ---
    # Act 1: Intake
    builder.add_node("collect_profile", collect_profile)
    builder.add_node("identify_income_sources", identify_income_sources)
    builder.add_node("determine_itr_form", determine_itr_form)
    builder.add_node("build_doc_checklist", build_doc_checklist)

    # Act 2: Documents
    builder.add_node("request_documents", request_documents)
    builder.add_node("parse_documents", parse_documents)
    builder.add_node("validate_extractions", validate_extractions)
    builder.add_node("human_doc_review", human_doc_review)

    # Act 3: Gap fill
    builder.add_node("gap_fill_chat", gap_fill_chat)
    builder.add_node("cross_check", cross_check)
    builder.add_node("aggregate_data", aggregate_data)

    # Act 4: Output + Advisor
    builder.add_node("compute_tax", compute_tax)
    builder.add_node("build_outputs", build_outputs)
    builder.add_node("tax_advisor", tax_advisor)
    builder.add_node("human_final_review", human_final_review)
    builder.add_node("finalise", finalise)

    # --- Entry point ---
    builder.set_entry_point("collect_profile")

    # --- Act 1 edges ---
    builder.add_edge("collect_profile", "identify_income_sources")
    builder.add_edge("identify_income_sources", "determine_itr_form")
    builder.add_edge("determine_itr_form", "build_doc_checklist")
    builder.add_edge("build_doc_checklist", "request_documents")

    # --- Act 2 edges ---
    builder.add_edge("request_documents", "parse_documents")
    builder.add_edge("parse_documents", "validate_extractions")
    builder.add_conditional_edges(
        "validate_extractions",
        route_after_validation,
        {"human_doc_review": "human_doc_review", "gap_fill_chat": "gap_fill_chat"},
    )
    builder.add_edge("human_doc_review", "gap_fill_chat")

    # --- Act 3 edges ---
    builder.add_edge("gap_fill_chat", "cross_check")
    builder.add_conditional_edges(
        "cross_check",
        route_after_cross_check,
        {"gap_fill_chat": "gap_fill_chat", "aggregate_data": "aggregate_data"},
    )
    builder.add_edge("aggregate_data", "compute_tax")

    # --- Act 4 edges ---
    builder.add_edge("compute_tax", "build_outputs")
    builder.add_edge("build_outputs", "tax_advisor")
    builder.add_conditional_edges(
        "tax_advisor",
        route_after_advisor,
        {"tax_advisor": "tax_advisor", "human_final_review": "human_final_review"},
    )
    builder.add_conditional_edges(
        "human_final_review",
        route_after_final_review,
        {"finalise": "finalise", "aggregate_data": "aggregate_data"},
    )
    builder.add_edge("finalise", END)

    # --- Compile ---
    # interrupt_before=["human_doc_review", "human_final_review"]
    #   Pause BEFORE these nodes so the API can inject user corrections/confirmation
    #   into state before the node actually runs.
    #
    # interrupt_after=["tax_advisor"]
    #   Run the advisor first (proactive opening message), THEN pause so the user
    #   can reply. Each resume runs the advisor once more, then pauses again.
    compile_kwargs = dict(
        interrupt_before=["human_doc_review", "human_final_review"],
        interrupt_after=["tax_advisor"],
    )
    if use_checkpointer:
        from inditr.graph.checkpointer import get_checkpointer
        checkpointer = get_checkpointer()
        return builder.compile(checkpointer=checkpointer, **compile_kwargs)
    else:
        return builder.compile(**compile_kwargs)
