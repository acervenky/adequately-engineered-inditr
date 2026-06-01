"""
Pydantic schema for Form 16 LLM extraction output.

This is the contract between the LLM extractor and the rest of the parser:
the LLM must return JSON matching these fields; Pydantic validates types and
coerces values before any number touches the engine.

All fields Optional — missing = null = confidence 0.0 = goes to human review.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class Form16ExtractionSchema(BaseModel):
    # ── Part A — TRACES-generated (usually reliable) ──────────────────────────
    employer_name: Optional[str] = Field(
        default=None,
        description="Full name of the employer / company",
    )
    employer_tan: Optional[str] = Field(
        default=None,
        description="Employer TAN (Tax Deduction Account Number), format: AAAA99999A",
    )
    employee_pan: Optional[str] = Field(
        default=None,
        description="Employee PAN (Permanent Account Number), format: AAAAA9999A",
    )
    employee_name: Optional[str] = Field(
        default=None,
        description="Full name of the employee as printed on Form 16",
    )
    financial_year: Optional[str] = Field(
        default=None,
        description="Financial year this Form 16 covers, e.g. '2025-26'",
    )
    total_tds_deposited: Optional[float] = Field(
        default=None,
        description="Total TDS deposited with government per Part A quarterly table, in rupees",
    )

    # ── Part B — payroll-software-generated (layout varies) ───────────────────
    gross_salary: Optional[float] = Field(
        default=None,
        description="Gross salary before any deductions, in rupees",
    )
    basic_salary: Optional[float] = Field(
        default=None,
        description="Basic salary component, in rupees",
    )
    hra_received: Optional[float] = Field(
        default=None,
        description="HRA (House Rent Allowance) received from employer, in rupees",
    )
    hra_exemption: Optional[float] = Field(
        default=None,
        description="HRA exemption claimed under Section 10(13A), in rupees",
    )
    standard_deduction: Optional[float] = Field(
        default=None,
        description="Standard deduction u/s 16(ia), max ₹75,000 (new regime) or ₹50,000 (old regime)",
    )
    professional_tax: Optional[float] = Field(
        default=None,
        description="Professional tax deducted u/s 16(iii), in rupees",
    )
    entertainment_allowance: Optional[float] = Field(
        default=None,
        description="Entertainment allowance deduction u/s 16(ii), typically only for government employees",
    )
    net_taxable_salary: Optional[float] = Field(
        default=None,
        description="Net income chargeable under head Salaries after Section 16 deductions, in rupees",
    )

    # ── Chapter VI-A deductions ────────────────────────────────────────────────
    deduction_80c: Optional[float] = Field(
        default=None,
        description="Total deduction under Section 80C (PPF, ELSS, LIC, etc.), max ₹1,50,000",
    )
    deduction_80ccd1b: Optional[float] = Field(
        default=None,
        description="Employee NPS contribution under Section 80CCD(1B), max ₹50,000",
    )
    deduction_80ccd2: Optional[float] = Field(
        default=None,
        description="Employer NPS contribution under Section 80CCD(2), max 14% of salary",
    )
    deduction_80d: Optional[float] = Field(
        default=None,
        description="Health insurance premium deduction under Section 80D, in rupees",
    )
    deduction_80e: Optional[float] = Field(
        default=None,
        description="Education loan interest deduction under Section 80E, in rupees",
    )
    deduction_80tta_ttb: Optional[float] = Field(
        default=None,
        description="Savings/bank interest deduction under 80TTA (max ₹10,000) or 80TTB for senior citizens (max ₹50,000)",
    )
    deduction_80g: Optional[float] = Field(
        default=None,
        description="Donations deduction under Section 80G, in rupees",
    )
    total_chapter_via: Optional[float] = Field(
        default=None,
        description="Total of all Chapter VI-A deductions, in rupees",
    )

    # ── Final computation figures ──────────────────────────────────────────────
    total_taxable_income: Optional[float] = Field(
        default=None,
        description="Total taxable income after all deductions, in rupees",
    )
    tax_payable: Optional[float] = Field(
        default=None,
        description="Income tax payable before TDS credit, in rupees",
    )
    tds_deducted: Optional[float] = Field(
        default=None,
        description="Total TDS deducted by employer per Part B, in rupees",
    )
    net_tax_payable_refundable: Optional[float] = Field(
        default=None,
        description="Net tax payable or refundable (positive = payable, negative = refund), in rupees",
    )
