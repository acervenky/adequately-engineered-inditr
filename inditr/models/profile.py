import re
from enum import Enum
from typing import Optional
from pydantic import BaseModel, field_validator, Field


class EmploymentType(str, Enum):
    SALARIED = "salaried"
    SELF_EMPLOYED = "self_employed"
    PENSIONER = "pensioner"
    OTHER = "other"


class IncomeSourceType(str, Enum):
    SALARY = "salary"
    HOUSE_PROPERTY = "house_property"
    CAPITAL_GAINS = "capital_gains"
    OTHER_SOURCES = "other_sources"
    BUSINESS = "business"


_PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


class FilerProfile(BaseModel):
    pan: str
    name: str
    date_of_birth: str  # ISO format YYYY-MM-DD
    employment_type: EmploymentType
    income_sources: list[IncomeSourceType] = Field(default_factory=list)
    residential_status: str = "resident"  # resident / non_resident / rnor
    email: Optional[str] = None
    mobile: Optional[str] = None

    @field_validator("pan")
    @classmethod
    def validate_pan(cls, v: str) -> str:
        v = v.strip().upper()
        if not _PAN_RE.match(v):
            raise ValueError(
                f"Invalid PAN format. Expected 5 alpha + 4 digit + 1 alpha uppercase, got: {v!r}"
            )
        return v

    @property
    def masked_pan(self) -> str:
        """Return PAN masked as XXXXX####X (4 digits preserved) for user-facing outputs."""
        return f"XXXXX{self.pan[5:9]}X"


class DocumentRequest(BaseModel):
    doc_type: str
    description: str
    mandatory: bool = True
    reason: Optional[str] = None
