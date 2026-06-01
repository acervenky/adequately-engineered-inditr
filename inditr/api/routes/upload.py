"""
File upload route.
POST /session/{id}/upload — multipart/form-data
"""
from __future__ import annotations
import asyncio
import os
import tempfile

from fastapi import APIRouter, HTTPException, UploadFile, File

from inditr.api.schemas import UploadResponse

router = APIRouter(prefix="/session", tags=["upload"])

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "text/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


@router.post("/{session_id}/upload", response_model=UploadResponse)
async def upload_document(session_id: str, file: UploadFile = File(...)) -> UploadResponse:
    """
    Upload a document, parse it with ParserRegistry, store in session.
    Returns ParsedDocument summary + low_confidence_fields.
    """
    from inditr.api.routes.session import get_graph
    from inditr.parsers.registry import ParserRegistry

    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    try:
        current_state = graph.get_state(config)
        if not current_state.values:
            raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")

    # Validate MIME type before reading the body
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime and mime not in _ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{mime}'. Allowed: PDF, JPEG, PNG, CSV, Excel.",
        )

    # Save upload to a temp dir using the ORIGINAL filename so parsers can
    # use the filename as a classification signal (e.g. "realizedPnL_EQ_…").
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(content) // (1024*1024)} MB). Maximum is 50 MB.",
        )

    safe_name = os.path.basename(file.filename or "upload.pdf").replace("..", "_")
    tmpdir = tempfile.mkdtemp(prefix="inditr_upload_")
    tmp_path = os.path.join(tmpdir, safe_name)
    with open(tmp_path, "wb") as tmp:
        tmp.write(content)

    doc = None
    try:
        registry = ParserRegistry()
        doc = await asyncio.to_thread(registry.parse, tmp_path)

        # Append parsed document to session state via graph.update_state.
        # Parsing is done at upload time; no file path stored (temp file deleted below).
        existing_docs = list(current_state.values.get("documents") or [])
        doc_dict = doc.model_dump()
        doc_dict["original_filename"] = file.filename
        existing_docs.append(doc_dict)
        graph.update_state(config, {"documents": existing_docs})

        # Identify low-confidence fields
        low_conf = [
            f"{doc.doc_type}/{fname} (conf={fdata.confidence:.0%})"
            for fname, fdata in doc.fields.items()
            if fdata.confidence < 0.85
        ]

    finally:
        try:
            os.unlink(tmp_path)
            os.rmdir(tmpdir)
        except Exception:
            pass

    if doc is None:
        raise HTTPException(status_code=500, detail="Document parsing failed")

    return UploadResponse(
        session_id=session_id,
        filename=file.filename or "unknown",
        doc_type=doc.doc_type,
        fields_extracted=len(doc.fields),
        low_confidence_fields=low_conf,
        parse_errors=doc.parse_errors,
        overall_confidence=doc.overall_confidence,
    )
