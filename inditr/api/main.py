"""
IndITR FastAPI application.
Run: uvicorn inditr.api.main:app --reload
"""
from __future__ import annotations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from inditr.api.schemas import HealthResponse
from inditr.api.routes.session import router as session_router
from inditr.api.routes.chat import router as chat_router
from inditr.api.routes.upload import router as upload_router

_DISCLAIMER = (
    "IndITR is an open-source tool for tax preparation assistance. "
    "It does not constitute professional tax advice. All computations must be "
    "verified by the user before filing. The authors assume no liability for "
    "errors, omissions, or penalties arising from use of this tool. "
    "When in doubt, consult a qualified Chartered Accountant."
)

app = FastAPI(
    title="IndITR API",
    description=(
        "Conversational Indian Tax Filing Agent -- AY 2026-27. "
        f"IMPORTANT: {_DISCLAIMER}"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(session_router)
app.include_router(chat_router)
app.include_router(upload_router)


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok", version="1.0.0", assessment_year="AY2026-27")


@app.get("/", tags=["health"])
async def root():
    return {
        "name": "IndITR",
        "description": "Indian Tax Filing Agent -- AY 2026-27",
        "docs": "/docs",
        "disclaimer": _DISCLAIMER,
    }
