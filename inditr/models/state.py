from typing import Any, Optional
from typing_extensions import TypedDict

# Forward-declared type aliases (avoid circular imports)
# All complex types are imported lazily or typed as Any
# to keep state.py dependency-free from other models.


class TaxFilingState(TypedDict, total=False):
    session_id: str
    assessment_year: str                    # e.g. "AY2024-25"
    messages: list[dict[str, Any]]          # LangGraph message history
    current_act: str                        # current graph node/action
    filer_profile: Optional[dict[str, Any]] # serialised FilerProfile
    itr_form: Optional[str]                 # "ITR-1" | "ITR-2"
    document_checklist: list[dict[str, Any]]
    documents: list[dict[str, Any]]         # serialised ParsedDocument list
    low_confidence_fields: list[str]        # field keys with confidence < 0.85
    gap_fill_answers: dict[str, Any]        # user-provided answers for gaps
    cross_check_results: list[dict[str, Any]]
    extracted_data: Optional[dict[str, Any]]  # serialised ExtractedTaxData
    computation: Optional[dict[str, Any]]     # serialised TaxComputation
    user_confirmed: bool
    itr_json: Optional[dict[str, Any]]
    regime_report: Optional[str]
    pdf_path: Optional[str]
    pending_clarifications: list[dict[str, Any]]
    errors: list[str]
    advisor_suggestions: list[str]          # proactive tips generated after computation
    whatif_history: list[dict[str, Any]]    # what-if scenario results shown to user
