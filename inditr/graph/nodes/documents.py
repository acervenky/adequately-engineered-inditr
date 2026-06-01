"""
Act 2 — Document nodes.
request_documents uses LLM.
parse_documents, validate_extractions are pure Python (no LLM).
human_doc_review uses LangGraph interrupt.
"""
from __future__ import annotations
from typing import Any

from inditr.models.state import TaxFilingState


def request_documents(state: TaxFilingState) -> dict[str, Any]:
    """
    Pure Python — format the structured document checklist into a clean message.
    No LLM: the checklist is already built by build_doc_checklist; we just
    present it clearly without letting a model add noise or markdown headers.
    """
    checklist = state.get("document_checklist", [])
    messages = list(state.get("messages", []))
    errors = list(state.get("errors", []))

    if not checklist:
        return {"current_act": "parse_documents", "messages": messages, "errors": errors}

    required = [d for d in checklist if d.get("mandatory")]
    optional = [d for d in checklist if not d.get("mandatory")]

    lines = ["Here's what I need from you for AY 2026-27. Upload each file using the button below.\n"]

    if required:
        lines.append("Must have:")
        for i, doc in enumerate(required, 1):
            lines.append(f"  {i}. {doc['description']}")

    if optional:
        lines.append("\nGood to have:")
        for i, doc in enumerate(optional, 1):
            hint = f" ({doc['reason']})" if doc.get("reason") else ""
            lines.append(f"  {i}. {doc['description']}{hint}")

    lines.append(
        "\nUpload what you have, then tell me when you're done "
        "— or just say which ones you don't have and I'll guide you."
    )

    reply = "\n".join(lines)
    new_messages = messages + [{"role": "assistant", "content": reply}]
    return {
        "messages": new_messages,
        "current_act": "parse_documents",
        "errors": errors,
    }


def parse_documents(state: TaxFilingState) -> dict[str, Any]:
    """
    NO LLM — documents are already parsed at upload time and stored in
    state['documents']. This node simply advances the graph to validation.

    (The legacy path of reading file paths from gap_fill_answers is removed:
    upload.py now deletes the temp file immediately after parsing, so paths
    stored there would be stale by the time this node runs.)
    """
    return {
        "documents": state.get("documents", []),
        "current_act": "validate_extractions",
        "errors": list(state.get("errors", [])),
    }


def validate_extractions(state: TaxFilingState) -> dict[str, Any]:
    """
    NO LLM — check overall_confidence, populate low_confidence_fields.
    Any field with confidence < 0.85 is flagged.
    """
    documents = state.get("documents", [])
    errors = list(state.get("errors", []))
    low_confidence: list[str] = []

    for doc in documents:
        doc_type = doc.get("doc_type", "unknown")
        fields = doc.get("fields", {})
        for field_name, field_data in fields.items():
            conf = field_data.get("confidence", 1.0)
            if conf < 0.85:
                low_confidence.append(f"{doc_type}/{field_name} (confidence={conf:.2f})")

    next_act = "human_doc_review" if low_confidence else "gap_fill_chat"
    return {
        "low_confidence_fields": low_confidence,
        "current_act": next_act,
        "errors": errors,
    }


def human_doc_review(state: TaxFilingState) -> dict[str, Any]:
    """
    Human review node — processes user corrections for low-confidence fields.

    LangGraph pauses BEFORE this node via interrupt_before=["human_doc_review"].
    The API reads low_confidence_fields from state, presents them to the user,
    and stores corrections in gap_fill_answers["doc_review_responses"] before
    resuming. When this node runs, the user's response is already in state.
    """
    messages = list(state.get("messages", []))
    low_conf = state.get("low_confidence_fields", [])
    gap_fill = dict(state.get("gap_fill_answers", {}))

    if not low_conf:
        return {"current_act": "gap_fill_chat"}

    n = len(low_conf)
    summary = "field" if n == 1 else f"{n} fields"
    ack = (
        f"Thanks for reviewing! I've noted your corrections for {summary}. "
        f"Let me ask a few more questions to complete your tax picture."
    )
    messages = messages + [{"role": "assistant", "content": ack}]

    return {
        "messages": messages,
        "low_confidence_fields": [],  # cleared after review
        "gap_fill_answers": gap_fill,
        "current_act": "gap_fill_chat",
    }
