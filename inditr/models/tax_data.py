import logging
from datetime import date
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator

_logger = logging.getLogger(__name__)


class GainType(str, Enum):
    STCG = "STCG"
    LTCG = "LTCG"


class AssetType(str, Enum):
    EQUITY = "equity"                        # Listed equity shares
    EQUITY_MF = "equity_mf"                 # Equity mutual funds (112A)
    DEBT_MF = "debt_mf"                     # Debt mutual funds
    IMMOVABLE_PROPERTY = "immovable_property"
    BUYBACK = "buyback"                      # Share buyback proceeds — taxed as CG from FY 2026-27
    OTHER = "other"


_LTCG_EXEMPT_ASSETS = {AssetType.EQUITY, AssetType.EQUITY_MF}

# Finance Act 2023: debt MF acquired on/after Apr 1, 2023 always taxed at slab rates.
_DEBT_MF_SLAB_CUTOFF = date(2023, 4, 1)
# Budget 2024: property acquired before Jul 23, 2024 may choose 20%+indexation or 12.5% flat.
_PROPERTY_INDEXATION_CUTOFF = date(2024, 7, 23)


class SalaryIncome(BaseModel):
    gross_salary: float = Field(ge=0.0)
    basic: Optional[float] = Field(default=None, ge=0.0)
    da: Optional[float] = Field(default=None, ge=0.0)           # Dearness Allowance
    hra_received: Optional[float] = Field(default=None, ge=0.0)
    hra_exemption: Optional[float] = Field(default=None, ge=0.0)
    lta: Optional[float] = Field(default=None, ge=0.0)
    other_allowances: float = Field(default=0.0, ge=0.0)
    perquisites: float = Field(default=0.0, ge=0.0)
    professional_tax: float = Field(default=0.0, ge=0.0)
    tds_deducted: float = Field(default=0.0, ge=0.0)
    # Section 80CCD(2): employer NPS contribution — deductible under BOTH regimes.
    # Budget 2025 raised private-sector limit from 10% to 14% of salary from FY 2025-26.
    # Parsed from Form 16 Part B; do NOT add manually in Chapter VI-A gap fill.
    employer_nps_80ccd2: float = Field(default=0.0, ge=0.0)
    employer_name: Optional[str] = None
    employer_tan: Optional[str] = None

    @property
    def basic_da(self) -> Optional[float]:
        """Basic + DA — used for HRA and 80CCD(2) computations."""
        if self.basic is None:
            return None
        return (self.basic or 0.0) + (self.da or 0.0)


class CapitalGain(BaseModel):
    gain_type: GainType
    asset_type: AssetType
    sale_value: float = Field(ge=0.0)
    cost_of_acquisition: float = Field(ge=0.0)
    gain_amount: float                          # can be negative (loss)
    isin: Optional[str] = None
    scrip_name: Optional[str] = None
    section_112a: bool = False                  # True if covered under Section 112A
    acquisition_date: Optional[date] = None     # Required for debt-MF and property cutoff rules
    indexed_cost: Optional[float] = None        # Indexed cost for property acquired before Jul 23, 2024

    @model_validator(mode="after")
    def warn_gain_inconsistency(self) -> "CapitalGain":
        """Log a warning when gain_amount doesn't match sale_value - cost_of_acquisition.
        Does NOT raise — broker statements may include brokerage/STT in the gain figure."""
        computed = self.sale_value - self.cost_of_acquisition
        if abs(computed - self.gain_amount) > 1.0:
            _logger.warning(
                "CapitalGain inconsistency for %s: declared gain_amount=%.2f but "
                "sale_value - cost_of_acquisition=%.2f. Using declared gain_amount.",
                self.scrip_name or self.isin or "unknown",
                self.gain_amount,
                computed,
            )
        return self

    @property
    def ltcg_exempt_eligible(self) -> bool:
        """LTCG exemption of ₹1,25,000 applies ONLY to equity and equity MF (112A)."""
        return self.gain_type == GainType.LTCG and self.asset_type in _LTCG_EXEMPT_ASSETS

    @property
    def is_post_apr2023_debt_mf(self) -> bool:
        """
        Post-Apr-2023 debt MF is always taxed at slab rates regardless of holding period
        (Finance Act 2023). If acquisition_date is unknown, assume post-cutoff (conservative).
        """
        if self.asset_type != AssetType.DEBT_MF:
            return False
        if self.acquisition_date is None:
            return True
        return self.acquisition_date >= _DEBT_MF_SLAB_CUTOFF

    @property
    def can_use_indexation(self) -> bool:
        """
        Property acquired before Jul 23, 2024: taxpayer may choose between
        20% with indexation OR 12.5% without indexation (Budget 2024 transitional provision).
        Requires indexed_cost to be provided.
        """
        if self.asset_type != AssetType.IMMOVABLE_PROPERTY:
            return False
        if self.acquisition_date is None or self.indexed_cost is None:
            return False
        return self.acquisition_date < _PROPERTY_INDEXATION_CUTOFF


class Deductions(BaseModel):
    # 80C — Life insurance, PPF, ELSS, etc. — max ₹1,50,000
    sec_80c: float = Field(default=0.0, ge=0.0)
    # 80D — Medical insurance premium
    sec_80d: float = Field(default=0.0, ge=0.0)
    # 80TTA — Interest on savings account — max ₹10,000 (non-seniors, old regime only)
    sec_80tta: float = Field(default=0.0, ge=0.0)
    # 80TTB — Interest on deposits — max ₹50,000 (senior citizens, old regime only)
    sec_80ttb: float = Field(default=0.0, ge=0.0)
    # 80CCD(1B) — Additional NPS contribution beyond 80C — max ₹50,000 (old regime only)
    sec_80ccd_1b: float = Field(default=0.0, ge=0.0)
    # HRA exemption (pre-computed by parser / deductions.compute_hra_exemption)
    hra_exemption: float = Field(default=0.0, ge=0.0)
    # Section 24b — home loan interest on self-occupied property (max ₹2L, old regime only)
    home_loan_interest: float = Field(default=0.0, ge=0.0)
    # Section 80E — Interest on education loan (self/spouse/children/legal ward)
    # Full interest deductible for up to 8 years from year repayment starts. Old regime only.
    sec_80e: float = Field(default=0.0, ge=0.0)
    # Section 80G — Donations to approved institutions (100% or 50% of eligible amount)
    # Cap: 10% of adjusted gross total income for some institutions. Old regime only.
    sec_80g: float = Field(default=0.0, ge=0.0)
    # Section 54 — LTCG from residential property reinvested in new residential property.
    # Full exemption if full LTCG reinvested. Available under BOTH regimes.
    sec_54_exemption: float = Field(default=0.0, ge=0.0)
    # Section 54EC — LTCG from any immovable property reinvested in NHAI/REC bonds.
    # Maximum ₹50,00,000 per financial year. Must invest within 6 months of sale.
    sec_54ec_exemption: float = Field(default=0.0, ge=0.0)
    # Section 54F — LTCG from non-residential capital asset reinvested in residential property.
    # Proportional exemption. Old regime only.
    sec_54f_exemption: float = Field(default=0.0, ge=0.0)
    # Other deductions (80GG, 80U, 80DD, etc. — declared as net eligible amount)
    other_deductions: float = Field(default=0.0, ge=0.0)

    @field_validator("sec_80c")
    @classmethod
    def cap_80c(cls, v: float) -> float:
        if v > 150_000.0:
            raise ValueError(f"80C deduction cannot exceed ₹1,50,000. Got: {v}")
        return v

    @field_validator("sec_80d")
    @classmethod
    def cap_80d(cls, v: float) -> float:
        # Absolute max: ₹50,000 self/family (senior) + ₹50,000 parents (senior) = ₹1,00,000.
        if v > 100_000.0:
            raise ValueError(f"80D deduction cannot exceed ₹1,00,000. Got: {v}")
        return v

    @field_validator("sec_80tta")
    @classmethod
    def cap_80tta(cls, v: float) -> float:
        if v > 10_000.0:
            raise ValueError(f"80TTA deduction cannot exceed ₹10,000. Got: {v}")
        return v

    @field_validator("sec_80ttb")
    @classmethod
    def cap_80ttb(cls, v: float) -> float:
        if v > 50_000.0:
            raise ValueError(f"80TTB deduction cannot exceed ₹50,000. Got: {v}")
        return v

    @field_validator("sec_80ccd_1b")
    @classmethod
    def cap_80ccd_1b(cls, v: float) -> float:
        if v > 50_000.0:
            raise ValueError(f"80CCD(1B) deduction cannot exceed ₹50,000. Got: {v}")
        return v

    @field_validator("sec_54ec_exemption")
    @classmethod
    def cap_54ec(cls, v: float) -> float:
        if v > 5_000_000.0:
            raise ValueError(f"Section 54EC exemption cannot exceed ₹50,00,000. Got: {v}")
        return v


class ExtractedTaxData(BaseModel):
    salary_income: Optional[SalaryIncome] = None
    capital_gains: list[CapitalGain] = Field(default_factory=list)
    other_income: float = Field(default=0.0, ge=0.0)
    house_property_income: float = Field(default=0.0)  # can be negative (loss)
    deductions: Deductions = Field(default_factory=Deductions)
    advance_tax_paid: float = Field(default=0.0, ge=0.0)
    tds_total: float = Field(default=0.0, ge=0.0)
    tcs_total: float = Field(default=0.0, ge=0.0)
