"""
Pydantic request/response models for all API endpoints.
"""
from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel


class StartSessionRequest(BaseModel):
    assessment_year: str = "AY2026-27"


class StartSessionResponse(BaseModel):
    session_id: str
    assessment_year: str
    message: str


class SessionStatusResponse(BaseModel):
    session_id: str
    current_act: Optional[str] = None
    itr_form: Optional[str] = None
    documents_uploaded: int = 0
    pending_clarifications: list[dict] = []
    errors: list[str] = []
    low_confidence_fields: list[str] = []
    messages: list[dict] = []           # full chat history for session restore
    interrupted_at: list[str] = []      # LangGraph next-node list when graph is paused


class SessionOutputsResponse(BaseModel):
    session_id: str
    itr_json: Optional[dict[str, Any]] = None
    regime_report: Optional[dict[str, Any]] = None
    pdf_path: Optional[str] = None
    ready: bool = False


class ConfirmSessionRequest(BaseModel):
    confirmed: bool = True


class ConfirmSessionResponse(BaseModel):
    session_id: str
    confirmed: bool
    message: str


class ChatMessageRequest(BaseModel):
    message: str
    role: str = "user"


class ChatMessageResponse(BaseModel):
    session_id: str
    assistant_message: str
    current_act: Optional[str] = None
    state_updates: dict[str, Any] = {}


class UploadResponse(BaseModel):
    session_id: str
    filename: str
    doc_type: str
    fields_extracted: int
    low_confidence_fields: list[str] = []
    parse_errors: list[str] = []
    overall_confidence: float


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "1.0.0"
    assessment_year: str = "AY2026-27"
