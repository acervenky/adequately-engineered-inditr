import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator


class ExtractedField(BaseModel):
    value: Any
    source_document: str
    source_page: Optional[int] = None
    source_section: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    raw_text: Optional[str] = None
    requires_review: bool = False

    @model_validator(mode="after")
    def set_requires_review(self) -> "ExtractedField":
        if self.confidence < 0.85:
            self.requires_review = True
        return self


class ParsedDocument(BaseModel):
    doc_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    doc_type: str
    filename: str
    pages: int = 0
    parsed_at: datetime = Field(default_factory=datetime.utcnow)
    fields: dict[str, ExtractedField] = Field(default_factory=dict)
    parse_errors: list[str] = Field(default_factory=list)
    overall_confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def compute_overall_confidence(self) -> "ParsedDocument":
        if self.fields:
            self.overall_confidence = min(f.confidence for f in self.fields.values())
        return self
