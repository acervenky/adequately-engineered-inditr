from typing import Literal, Optional
from pydantic import BaseModel, Field


class SlabBreakdown(BaseModel):
    slab_label: str          # e.g. "0–3L", "3L–6L"
    rate: float              # e.g. 0.05 for 5%
    taxable_amount: float = Field(ge=0.0)
    tax: float = Field(ge=0.0)


class RegimeResult(BaseModel):
    regime: Literal["old", "new"]
    gross_income: float = Field(ge=0.0)
    standard_deduction: float = Field(ge=0.0)
    total_deductions: float = Field(ge=0.0)
    taxable_income: float = Field(ge=0.0)
    slab_breakdown: list[SlabBreakdown] = Field(default_factory=list)
    income_tax: float = Field(ge=0.0)
    surcharge: float = Field(default=0.0, ge=0.0)
    health_education_cess: float = Field(ge=0.0)
    rebate_87a: float = Field(default=0.0, ge=0.0)
    total_tax_liability: float = Field(ge=0.0)
    tds_tcs_advance_tax: float = Field(default=0.0, ge=0.0)
    net_payable_refundable: float  # negative = refund


class TaxComputation(BaseModel):
    old_regime: RegimeResult
    new_regime: RegimeResult
    recommended_regime: Literal["old", "new"]
    savings_from_recommendation: float = Field(ge=0.0)
    recommendation_reason: str
