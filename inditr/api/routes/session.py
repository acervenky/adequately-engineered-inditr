"""
Session management routes.
POST /session/start                          - create session and kick off the LangGraph agent
GET  /session/{id}                           - session status (current node, interrupts, errors)
GET  /session/{id}/outputs                   - ITR JSON + regime report + PDF path
GET  /session/{id}/download/itr-json         - download ITR JSON as file (internal schema)
GET  /session/{id}/download/itr-json-official - download IT-Dept conformant JSON for offline utility
GET  /session/{id}/download/pdf              - download PDF summary
POST /session/{id}/confirm                   - resume after human_final_review interrupt
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import uuid
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, FileResponse

from inditr.api.schemas import (
    StartSessionRequest, StartSessionResponse,
    SessionStatusResponse, SessionOutputsResponse,
    ConfirmSessionRequest, ConfirmSessionResponse,
)

router = APIRouter(prefix="/session", tags=["session"])
logger = logging.getLogger(__name__)


# -- Compiled graph singleton --------------------------------------------------

@lru_cache(maxsize=1)
def get_graph():
    from inditr.graph.graph import build_graph
    return build_graph(use_checkpointer=True)


def _config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _get_state(session_id: str):
    graph = get_graph()
    config = _config(session_id)
    try:
        state = graph.get_state(config)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found: {e}")
    if not state.values:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return state


# -- Initial state factory -----------------------------------------------------

def _initial_state(session_id: str, assessment_year: str) -> dict:
    return {
        "session_id": session_id,
        "assessment_year": assessment_year,
        "messages": [],
        "current_act": "collect_profile",
        "filer_profile": None,
        "itr_form": None,
        "document_checklist": [],
        "documents": [],
        "low_confidence_fields": [],
        "gap_fill_answers": {},
        "cross_check_results": [],
        "extracted_data": None,
        "computation": None,
        "user_confirmed": False,
        "itr_json": None,
        "regime_report": None,
        "pdf_path": None,
        "pending_clarifications": [],
        "errors": [],
        "advisor_suggestions": [],
        "whatif_history": [],
    }


# -- Helpers -------------------------------------------------------------------

def _build_itr_json_internal(values: dict):
    """Build internal ITR JSON from session state. Returns None if data unavailable."""
    if not (values.get("computation") and values.get("extracted_data") and values.get("filer_profile")):
        return None
    try:
        from inditr.models.computation import TaxComputation
        from inditr.models.tax_data import ExtractedTaxData
        from inditr.models.profile import FilerProfile
        from inditr.output_builders.itr_json import map_to_itr1, map_to_itr2
        comp = TaxComputation(**values["computation"])
        data = ExtractedTaxData(**values["extracted_data"])
        profile = FilerProfile(**values["filer_profile"])
        itr_form = values.get("itr_form", "ITR-1")
        return map_to_itr2(data, comp, profile) if itr_form == "ITR-2" else map_to_itr1(data, comp, profile)
    except Exception as exc:
        logger.warning("Could not build ITR JSON for session: %s", exc)
        return None


# -- Routes --------------------------------------------------------------------

@router.post("/start", response_model=StartSessionResponse)
async def start_session(req: StartSessionRequest) -> StartSessionResponse:
    graph = get_graph()
    session_id = str(uuid.uuid4())
    config = _config(session_id)
    initial_input = _initial_state(session_id, req.assessment_year)
    initial_input["messages"] = [{
        "role": "user",
        "content": "Hi! I want to file my ITR for AY 2026-27.",
    }]
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, graph.invoke, initial_input, config)
    state = graph.get_state(config)
    values = state.values or {}
    greeting = next(
        (m["content"] for m in (values.get("messages") or []) if m.get("role") == "assistant"),
        "Session started. Please introduce yourself (name, PAN, date of birth).",
    )
    return StartSessionResponse(
        session_id=session_id,
        assessment_year=req.assessment_year,
        message=greeting,
    )


@router.get("/{session_id}", response_model=SessionStatusResponse)
async def get_session(session_id: str) -> SessionStatusResponse:
    state = _get_state(session_id)
    values = state.values or {}
    return SessionStatusResponse(
        session_id=session_id,
        current_act=values.get("current_act"),
        itr_form=values.get("itr_form"),
        documents_uploaded=len(values.get("documents") or []),
        pending_clarifications=values.get("pending_clarifications") or [],
        errors=values.get("errors") or [],
        low_confidence_fields=values.get("low_confidence_fields") or [],
        messages=values.get("messages") or [],
        interrupted_at=list(state.next) if state.next else [],
    )


@router.get("/{session_id}/outputs", response_model=SessionOutputsResponse)
async def get_outputs(session_id: str) -> SessionOutputsResponse:
    """Return filing outputs (available after finalise node completes)."""
    state = _get_state(session_id)
    values = state.values or {}

    itr_raw = values.get("itr_json")
    regime_raw = values.get("regime_report")
    pdf_path = values.get("pdf_path")

    regime_report_dict = None
    if isinstance(regime_raw, dict):
        regime_report_dict = regime_raw
    elif isinstance(regime_raw, str) and regime_raw:
        regime_report_dict = {"text_report": regime_raw}
        computation_raw = values.get("computation")
        if computation_raw:
            try:
                from inditr.models.computation import TaxComputation
                comp = TaxComputation(**computation_raw)
                regime_report_dict.update({
                    "old_tax": float(comp.old_regime.total_tax_liability),
                    "new_tax": float(comp.new_regime.total_tax_liability),
                    "recommendation": comp.recommended_regime,
                    "savings": float(comp.savings_from_recommendation),
                    "reason": comp.recommendation_reason,
                })
            except Exception:
                pass

    if not itr_raw:
        itr_raw = _build_itr_json_internal(values)

    return SessionOutputsResponse(
        session_id=session_id,
        itr_json=itr_raw,
        regime_report=regime_report_dict,
        pdf_path=pdf_path,
        ready=bool(itr_raw or regime_report_dict),
    )


@router.get("/{session_id}/download/itr-json")
async def download_itr_json(session_id: str) -> Response:
    """
    Download ITR JSON (IndITR internal schema) as a file attachment.
    Use /download/itr-json-official for IT Department portal / offline utility upload.
    """
    state = _get_state(session_id)
    values = state.values or {}
    itr_raw = values.get("itr_json") or _build_itr_json_internal(values)
    if not itr_raw:
        raise HTTPException(
            status_code=404,
            detail="ITR JSON not yet available. Complete the filing flow first.",
        )
    itr_form = values.get("itr_form", "ITR-1")
    filename = f"IndITR_{session_id[:8]}_{itr_form.replace('-', '')}_AY2026-27.json"
    return Response(
        content=json.dumps(itr_raw, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{session_id}/download/itr-json-official")
async def download_itr_json_official(session_id: str) -> Response:
    """
    Download ITR JSON conforming to the IT Dept AY 2026-27 offline utility schema.
    Import into the offline utility, verify all schedules, then upload on the portal.

    Schema reference:
    https://www.incometaxindia.gov.in/Pages/downloads/income-tax-return.aspx
    """
    state = _get_state(session_id)
    values = state.values or {}
    if not (values.get("computation") and values.get("extracted_data") and values.get("filer_profile")):
        raise HTTPException(
            status_code=404,
            detail="Computation not yet available. Complete the filing flow first.",
        )
    try:
        from inditr.models.computation import TaxComputation
        from inditr.models.tax_data import ExtractedTaxData
        from inditr.models.profile import FilerProfile
        from inditr.output_builders.itr_json import map_to_official_itr1, map_to_official_itr2
        comp = TaxComputation(**values["computation"])
        data = ExtractedTaxData(**values["extracted_data"])
        profile = FilerProfile(**values["filer_profile"])
        itr_form = values.get("itr_form", "ITR-1")
        official = (
            map_to_official_itr2(data, comp, profile)
            if itr_form == "ITR-2"
            else map_to_official_itr1(data, comp, profile)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not build official ITR JSON: {e}")

    itr_form_clean = itr_form.replace("-", "")
    filename = f"ITR_AY2026_27_{itr_form_clean}_{session_id[:8]}.json"
    return Response(
        content=json.dumps(official, indent=2, ensure_ascii=False),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{session_id}/download/pdf")
async def download_pdf(session_id: str) -> FileResponse:
    """Download the PDF tax summary (includes portal filing walkthrough)."""
    state = _get_state(session_id)
    values = state.values or {}
    pdf_path = values.get("pdf_path")
    if not pdf_path or not os.path.exists(pdf_path):
        raise HTTPException(
            status_code=404,
            detail="PDF not yet available. Complete the filing flow first.",
        )
    itr_form = values.get("itr_form", "ITR-1")
    filename = f"IndITR_{session_id[:8]}_{itr_form.replace('-', '')}_AY2026-27.pdf"
    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{session_id}/confirm", response_model=ConfirmSessionResponse)
async def confirm_session(
    session_id: str, req: ConfirmSessionRequest
) -> ConfirmSessionResponse:
    """
    Resume after the human_final_review interrupt.
    If confirmed, the graph runs finalise (writes ITR JSON + PDF).
    If not confirmed, the graph routes back to aggregate_data for revision.
    """
    graph = get_graph()
    config = _config(session_id)
    try:
        state = graph.get_state(config)
        if not state.values:
            raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    loop = asyncio.get_event_loop()
    graph.update_state(config, {"user_confirmed": req.confirmed})
    await loop.run_in_executor(None, graph.invoke, None, config)

    return ConfirmSessionResponse(
        session_id=session_id,
        confirmed=req.confirmed,
        message=(
            "Tax computation confirmed. Your ITR JSON and PDF are ready."
            if req.confirmed
            else "Computation not confirmed. Go back and revise."
        ),
    )
