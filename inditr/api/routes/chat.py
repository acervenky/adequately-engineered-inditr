"""
Chat route — drive the LangGraph agent.
POST /session/{id}/message
"""
from __future__ import annotations
from typing import Any

from fastapi import APIRouter, HTTPException

from inditr.api.schemas import ChatMessageRequest, ChatMessageResponse

router = APIRouter(prefix="/session", tags=["chat"])


def _get_graph():
    """Return the compiled LangGraph instance (lazy singleton via session module)."""
    from inditr.api.routes.session import get_graph
    return get_graph()


def _config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _latest_assistant_message(values: dict) -> str:
    """Extract the most recently added assistant message from state."""
    msgs = values.get("messages") or []
    for m in reversed(msgs):
        if m.get("role") == "assistant":
            return m.get("content", "")
    return ""


@router.post("/{session_id}/message", response_model=ChatMessageResponse)
async def send_message(session_id: str, req: ChatMessageRequest) -> ChatMessageResponse:
    """
    Append a user message to state and advance the LangGraph agent.

    Flow:
      1. Verify the session thread exists in the checkpointer.
      2. Add the user message to the current state via update_state.
      3. Resume the graph (invoke with None — uses checkpointed state).
      4. Detect whether the graph is now interrupted (waiting for human input).
      5. Return the latest assistant message and session status.

    The graph handles all routing internally via its compiled edges.
    interrupt_before=["human_doc_review", "human_final_review"] pauses the
    graph so the API can inject corrections/confirmation before those nodes run.
    interrupt_after=["tax_advisor"] pauses after the advisor gives its response
    so the user can reply before the next advisor turn.
    """
    graph = _get_graph()
    config = _config(session_id)

    # Verify session exists
    try:
        current = graph.get_state(config)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")

    if not current.values:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")

    # Append user message to state
    messages = list(current.values.get("messages") or [])
    messages.append({"role": req.role, "content": req.message})
    graph.update_state(config, {"messages": messages})

    assistant_message = ""
    errors: list[str] = []

    try:
        # Resume the graph from the current checkpoint.
        # None input = use checkpointed state (standard LangGraph resume pattern).
        result = graph.invoke(None, config)

        # Get updated state (post-invoke)
        new_state = graph.get_state(config)
        values = new_state.values or {}

        assistant_message = _latest_assistant_message(values)
        errors = list(values.get("errors") or [])

        # If no assistant message was added this turn (e.g. pure Python pipeline
        # ran silently), synthesise a progress message so the user isn't left hanging.
        if not assistant_message or assistant_message in [
            m.get("content") for m in messages if m.get("role") == "assistant"
        ]:
            next_nodes = new_state.next
            if next_nodes:
                assistant_message = (
                    f"Processing... waiting at: {', '.join(next_nodes)}"
                )

        state_updates: dict[str, Any] = {
            "current_act": values.get("current_act"),
            "itr_form": values.get("itr_form"),
            "interrupted_at": list(new_state.next) if new_state.next else [],
            "errors": errors,
        }

    except Exception as e:
        assistant_message = f"An error occurred: {e}"
        state_updates = {"error": str(e)}

    return ChatMessageResponse(
        session_id=session_id,
        assistant_message=assistant_message,
        current_act=graph.get_state(config).values.get("current_act"),
        state_updates=state_updates,
    )
