"""
Pydantic schema for bank statement LLM extraction.

The LLM returns a list of transactions; Pydantic validates types before
any value reaches the engine. Classification (salary vs broker vs FD interest)
is done by deterministic Python after validation.

All fields Optional — missing = null = confidence 0.0 = goes to human review.
"""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


class BankTransaction(BaseModel):
    date: Optional[str] = Field(
        default=None,
        description=(
            "Transaction date in DD-MM-YYYY or YYYY-MM-DD format. "
            "Leave null if the line has no date (it belongs to the previous transaction)."
        ),
    )
    particulars: str = Field(
        description=(
            "Full transaction description. For NEFT/UPI/IMPS entries concatenate "
            "all continuation lines into a single string."
        ),
    )
    credit_amount: Optional[float] = Field(
        default=None,
        description=(
            "Amount credited (deposited) to the account in rupees. "
            "Numeric only, no commas or currency symbol. Null if this is a debit."
        ),
    )
    debit_amount: Optional[float] = Field(
        default=None,
        description=(
            "Amount debited (withdrawn) from the account in rupees. "
            "Numeric only, no commas or currency symbol. Null if this is a credit."
        ),
    )
    balance: Optional[float] = Field(
        default=None,
        description="Running balance after this transaction, in rupees.",
    )


class BankStatementExtractionSchema(BaseModel):
    bank_name: Optional[str] = Field(
        default=None,
        description="Full name of the bank (e.g. 'Canara Bank', 'HDFC Bank').",
    )
    account_number_masked: Optional[str] = Field(
        default=None,
        description="Account number as shown, usually masked (e.g. 'XXXXXXXXX1128').",
    )
    account_holder_name: Optional[str] = Field(
        default=None,
        description="Name of the account holder as printed on the statement.",
    )
    period_from: Optional[str] = Field(
        default=None,
        description="Statement period start date (DD-MM-YYYY or YYYY-MM-DD).",
    )
    period_to: Optional[str] = Field(
        default=None,
        description="Statement period end date.",
    )
    opening_balance: Optional[float] = Field(
        default=None,
        description="Opening balance in rupees.",
    )
    closing_balance: Optional[float] = Field(
        default=None,
        description="Closing balance in rupees.",
    )
    transactions: list[BankTransaction] = Field(
        default_factory=list,
        description=(
            "All transactions on this page/chunk in chronological order. "
            "Each multi-line particulars entry must be merged into a single transaction object."
        ),
    )
