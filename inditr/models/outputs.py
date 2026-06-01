from typing import Literal, Optional
from pydantic import BaseModel, Field


class Clarification(BaseModel):
    field_name: str
    question: str
    context: Optional[str] = None
    answer: Optional[str] = None


class CrossCheckResult(BaseModel):
    check: str
    passed: bool
    severity: Literal["pass", "warning", "critical"]
    message: str


class FilingOutputs(BaseModel):
    itr_json_path: Optional[str] = None
    regime_report_path: Optional[str] = None
    pdf_path: Optional[str] = None
    filing_summary: Optional[str] = None
    disclaimer: str = (
        "IndITR is an open-source tool for tax preparation assistance. "
        "It does not constitute professional tax advice. All computations must be "
        "verified by the user before filing. The authors assume no liability for "
        "errors, omissions, or penalties arising from use of this tool. "
        "When in doubt, consult a qualified Chartered Accountant."
    )
