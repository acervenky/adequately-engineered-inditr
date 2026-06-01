"""
ITR JSON builders — ZERO LLM. Pure deterministic mapping.
Every field traced to ExtractedTaxData or TaxComputation.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from inditr.models.tax_data import ExtractedTaxData
from inditr.models.computation import TaxComputation
from inditr.models.profile import FilerProfile

_DISCLAIMER = (
    "IndITR is an open-source tool for tax preparation assistance. "
    "It does not constitute professional tax advice. All computations must be "
    "verified by the user before filing. The authors assume no liability for "
    "errors, omissions, or penalties arising from use of this tool. "
    "When in doubt, consult a qualified Chartered Accountant."
)

_SCHEMA_DIR = Path(__file__).parent.parent.parent / "data" / "itr_schemas"


def _mask_pan(pan: str) -> str:
    """Mask PAN as XXXXX####X for all user-facing outputs."""
    if len(pan) == 10:
        return f"XXXXX{pan[5:9]}X"
    return "XXXXXXXXXX"


def _personal_info(profile: FilerProfile) -> dict:
    return {
        "Name": profile.name,
        "PAN": _mask_pan(profile.pan),
        "DOB": profile.date_of_birth,
        "ResidentialStatus": profile.residential_status,
    }


def _income_details_base(data: ExtractedTaxData, regime: str) -> dict:
    std_ded = 75_000 if regime == "new" else 50_000
    gross_salary = float(data.salary_income.gross_salary) if data.salary_income else 0.0
    net_salary = max(0.0, gross_salary - std_ded)
    return {
        "GrossSalary": gross_salary,
        "StandardDeduction": float(std_ded),
        "NetSalary": net_salary,
        "OtherIncome": float(data.other_income),
    }


def _deductions_dict(data: ExtractedTaxData, regime: str = "new", age: int = 35) -> dict:
    """
    Build deductions summary for ITR JSON output.
    TotalDeductions uses the engine's compute_total_deductions for accuracy —
    this is the authoritative total used in tax computation, not a manual sum.
    """
    from inditr.engine.deductions import compute_total_deductions
    d = data.deductions
    sal = data.salary_income
    employer_nps = float(sal.employer_nps_80ccd2) if sal else 0.0
    professional_tax = float(sal.professional_tax) if sal else 0.0
    total = compute_total_deductions(
        d, regime, age=age,
        employer_nps_80ccd2=int(employer_nps),
        professional_tax=int(professional_tax),
    )
    return {
        "Sec80C": float(d.sec_80c),
        "Sec80D": float(d.sec_80d),
        "Sec80TTA": float(d.sec_80tta),
        "Sec80TTB": float(d.sec_80ttb),
        "Sec80CCD1B": float(d.sec_80ccd_1b),
        "Sec80CCD2EmployerNPS": employer_nps,
        "Sec80E": float(d.sec_80e),
        "Sec80G": float(d.sec_80g),
        "HRAExemption": float(d.hra_exemption),
        "HomeLoanInterest24b": float(d.home_loan_interest),
        "Sec54Exemption": float(d.sec_54_exemption),
        "Sec54ECExemption": float(d.sec_54ec_exemption),
        "Sec54FExemption": float(d.sec_54f_exemption),
        "OtherDeductions": float(d.other_deductions),
        "TotalDeductions": float(total),
    }


def map_to_itr1(
    data: ExtractedTaxData,
    computation: TaxComputation,
    profile: FilerProfile,
) -> dict[str, Any]:
    """
    Map ExtractedTaxData + TaxComputation to ITR-1 JSON structure.
    ZERO LLM. Every field traced to model inputs.
    """
    rec = computation.recommended_regime
    r = computation.new_regime if rec == "new" else computation.old_regime

    income = _income_details_base(data, rec)
    income["GrossIncome"] = income["GrossSalary"] + income["OtherIncome"]

    return {
        "AssessmentYear": "2026-27",
        "Form": "ITR-1",
        "PersonalInfo": _personal_info(profile),
        "IncomeDetails": income,
        "Deductions": _deductions_dict(data, regime=rec, age=_age_from_profile(profile)),
        "TaxComputation": {
            "RecommendedRegime": rec,
            "TaxableIncome": float(r.taxable_income),
            "IncomeTax": float(r.income_tax),
            "Surcharge": float(r.surcharge),
            "HealthEducationCess": float(r.health_education_cess),
            "Rebate87A": float(r.rebate_87a),
            "TotalTaxLiability": float(r.total_tax_liability),
            "TDSPaid": float(r.tds_tcs_advance_tax),
            "NetPayable": float(r.net_payable_refundable),
        },
        "Disclaimer": _DISCLAIMER,
    }


def map_to_itr2(
    data: ExtractedTaxData,
    computation: TaxComputation,
    profile: FilerProfile,
) -> dict[str, Any]:
    """
    Map ExtractedTaxData + TaxComputation to ITR-2 JSON structure.
    Includes capital gains schedule. ZERO LLM.
    """
    from inditr.engine.capital_gains import aggregate_gains
    from inditr.models.tax_data import GainType, AssetType

    rec = computation.recommended_regime
    r = computation.new_regime if rec == "new" else computation.old_regime

    income = _income_details_base(data, rec)
    income["HousePropertyIncome"] = float(data.house_property_income)

    # Capital gains — use aggregate_gains to correctly apply Section 74 set-offs
    cg_summary = aggregate_gains(data.capital_gains)
    stcg_equity = float(cg_summary["stcg_equity_total"])
    stcg_other  = float(cg_summary["stcg_other_total"])
    ltcg_equity = float(cg_summary["ltcg_equity_total"])
    ltcg_other  = float(cg_summary["ltcg_other_total"])

    income["CapitalGains"] = {
        "STCGEquity": stcg_equity,
        "LTCGEquity": ltcg_equity,
        "STCGOther":  stcg_other,
        "LTCGOther":  ltcg_other,
        "TotalSTCG":  stcg_equity + stcg_other,
        "TotalLTCG":  ltcg_equity + ltcg_other,
    }
    income["OtherIncome"] = float(data.other_income)
    income["GrossIncome"] = (
        income["GrossSalary"]
        + float(data.house_property_income)
        + income["CapitalGains"]["TotalSTCG"]
        + income["CapitalGains"]["TotalLTCG"]
        + income["OtherIncome"]
    )

    return {
        "AssessmentYear": "2026-27",
        "Form": "ITR-2",
        "PersonalInfo": _personal_info(profile),
        "IncomeDetails": income,
        "Deductions": _deductions_dict(data, regime=rec, age=_age_from_profile(profile)),
        "CapitalGainsSummary": {
            "STCG_111A_Equity": float(cg_summary["stcg_equity_total"]),
            "LTCG_112A_Equity": float(cg_summary["ltcg_equity_total"]),
            "LTCGProperty": float(cg_summary["ltcg_property_total"]),
            "SlabRateCG": float(cg_summary["slab_cg_total"]),
            "Sec54Exemption": float(data.deductions.sec_54_exemption),
            "Sec54ECExemption": float(data.deductions.sec_54ec_exemption),
            "Sec54FExemption": float(data.deductions.sec_54f_exemption),
        },
        "TaxComputation": {
            "RecommendedRegime": rec,
            "TaxableIncome": float(r.taxable_income),
            "IncomeTax": float(r.income_tax),
            "CapitalGainsTax": float(cg_summary["stcg_111a_tax"] + cg_summary["ltcg_112a_tax"] + cg_summary["ltcg_property_tax"] + cg_summary["ltcg_other_tax"]),
            "Surcharge": float(r.surcharge),
            "HealthEducationCess": float(r.health_education_cess),
            "Rebate87A": float(r.rebate_87a),
            "TotalTaxLiability": float(r.total_tax_liability),
            "TDSPaid": float(r.tds_tcs_advance_tax),
            "NetPayable": float(r.net_payable_refundable),
        },
        "Disclaimer": _DISCLAIMER,
    }


def validate_against_schema(itr_dict: dict, schema_path: str) -> list[str]:
    """
    Validate ITR dict against JSON schema.
    Returns list of validation errors (empty = valid).
    """
    import jsonschema

    errors = []
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
        jsonschema.validate(instance=itr_dict, schema=schema)
    except jsonschema.ValidationError as e:
        errors.append(f"Schema validation error: {e.message} at {list(e.path)}")
    except jsonschema.SchemaError as e:
        errors.append(f"Invalid schema: {e.message}")
    except FileNotFoundError:
        errors.append(f"Schema file not found: {schema_path}")
    except Exception as e:
        errors.append(f"Validation error: {e}")
    return errors


# ── Official IT-Dept JSON schema conformance (AY 2026-27) ─────────────────────
#
# The Income Tax Department's offline utility and bulk-upload API expect a
# specific JSON envelope. The structure below mirrors the ITR-1 (SAHAJ) and
# ITR-2 JSON schemas published with the offline utilities for AY 2026-27,
# derived from the department's XSD specifications.
#
# NOTE: Verify against the latest official utility before submitting.
# Download utility: https://www.incometaxindia.gov.in/Pages/downloads/income-tax-return.aspx
#
# Fields use the department's exact camelCase / PascalCase names.
# Monetary amounts are integers (paise stripped — department schema uses whole rupees).

def _int(val) -> int:
    """Convert Decimal/float to int (whole rupees, as required by the schema)."""
    try:
        return max(0, int(round(float(val))))
    except (TypeError, ValueError):
        return 0


def _dob_fmt(dob: str) -> str:
    """Convert YYYY-MM-DD to DD/MM/YYYY (department schema format)."""
    try:
        from datetime import datetime
        return datetime.strptime(dob, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return dob


def _age_from_profile(profile: "FilerProfile") -> int:
    """Age as of 31-Mar-2026 (AY 2026-27 reference date), same as engine."""
    from datetime import date
    dob = date.fromisoformat(profile.date_of_birth)
    ref = date(2026, 3, 31)
    age = ref.year - dob.year
    if (ref.month, ref.day) < (dob.month, dob.day):
        age -= 1
    return age


def map_to_official_itr1(
    data: ExtractedTaxData,
    computation: TaxComputation,
    profile: FilerProfile,
) -> dict[str, Any]:
    """
    Produce ITR-1 JSON conforming to the IT Dept AY 2026-27 offline utility schema.
    ZERO LLM. Every field mapped from validated model objects.

    Top-level envelope:  { "ITR": { "ITR1": { ... } } }
    """
    rec = computation.recommended_regime
    r = computation.new_regime if rec == "new" else computation.old_regime

    gross_salary = _int(data.salary_income.gross_salary) if data.salary_income else 0
    std_ded = 75_000 if rec == "new" else 50_000
    net_salary = max(0, gross_salary - std_ded)

    age = _age_from_profile(profile)
    d = data.deductions
    from inditr.engine.deductions import compute_total_deductions
    sal = data.salary_income
    employer_nps = _int(sal.employer_nps_80ccd2) if sal else 0
    professional_tax = _int(sal.professional_tax) if sal else 0
    total_ded = _int(
        compute_total_deductions(
            d, rec, age=age,
            employer_nps_80ccd2=employer_nps,
            professional_tax=professional_tax,
        )
    )

    return {
        "ITR": {
            "ITR1": {
                "CreationInfo": {
                    "SWVersionNo": "1.0",
                    "SWCreatedBy": "IndITR",
                    "JSONCreatedBy": "IndITR",
                    "JSONCreationDate": __import__("datetime").date.today().strftime("%d/%m/%Y"),
                    "InterfaceCode": "O",          # O = offline utility
                    "XMLtoJSONVersionNo": "V1.0.1",
                },
                "Form_ITR1": {
                    "FormName": "ITR-1",
                    "Description": "For individuals having income from salaries, one house property, other sources",
                    "AssessmentYear": "2026-27",
                    "SchemaVer": "Ver1.0",
                    "FormVer": "Ver1.0",
                },
                "PersonalInfo": {
                    "AsseseeeName": profile.name,
                    "PAN": profile.pan,           # UNMASKED — required for filing
                    "DOB": _dob_fmt(profile.date_of_birth),
                    "AadhaarCardNo": "",           # optional; leave blank
                    "ResidentialStatus": "RES",    # RES / NOR / NRI
                    "FilingStatus": {
                        "ReturnFileSec": "11",     # 11 = 139(1) original return
                        "OptOutNewTaxRegime": "N" if rec == "new" else "Y",
                    },
                },
                "IncomeDeductions": {
                    "GrossSalary": gross_salary,
                    "Salary": gross_salary,
                    "AllwncExemptUs10": 0,
                    "NetSalary": net_salary,
                    "DeductionUs16": std_ded,
                    "ProfessionalTax": professional_tax,
                    "GrossIncomeSalary": max(0, gross_salary - std_ded - professional_tax),
                    "IncomeOthSrc": _int(data.other_income),
                    "GrossTotalIncome": _int(r.gross_income),
                    # Chapter VI-A deductions (0 under new regime except 80CCD2)
                    "UsrDeductUndChapVIA": {
                        "Section80C": _int(d.sec_80c) if rec == "old" else 0,
                        "Section80CCC": 0,
                        "Section80CCDEmployeeOrSE": 0,
                        "Section80CCDEmployer": employer_nps,  # available both regimes
                        "Section80CCDO": _int(d.sec_80ccd_1b) if rec == "old" else 0,
                        "Section80D": _int(d.sec_80d) if rec == "old" else 0,
                        "Section80DD": 0,
                        "Section80DDB": 0,
                        "Section80E": _int(d.sec_80e) if rec == "old" else 0,
                        "Section80EE": 0,
                        "Section80EEA": 0,
                        "Section80EEB": 0,
                        "Section80G": _int(d.sec_80g) if rec == "old" else 0,
                        "Section80GG": 0,
                        "Section80GGA": 0,
                        "Section80GGC": 0,
                        "Section80TTA": _int(d.sec_80tta) if rec == "old" else 0,
                        "Section80TTB": _int(d.sec_80ttb) if rec == "old" else 0,
                        "Section80U": 0,
                        "TotalChapVIADeductions": total_ded,
                    },
                    "TotalIncome": _int(r.taxable_income),
                },
                "TaxComputation": {
                    "TaxPayableOnTI": _int(r.income_tax),
                    "Rebate87A": _int(r.rebate_87a),
                    "TaxPayableAfterRebate": max(0, _int(r.income_tax) - _int(r.rebate_87a)),
                    "Surcharge25": 0,
                    "TotalSurcharge": _int(r.surcharge),
                    "EducationCess": _int(r.health_education_cess),
                    "GrossTaxLiability": _int(r.total_tax_liability),
                    "TaxReliefUs89": 0,
                    "NetTaxLiability": _int(r.total_tax_liability),
                    "TotalTaxPayable": _int(r.total_tax_liability),
                },
                "TDSonSalaries": {
                    "TDSSalaryDeductor": [
                        {
                            "EmployerOrDeductorOrCollectTAN": data.salary_income.employer_tan if data.salary_income and hasattr(data.salary_income, "employer_tan") else "",
                            "EmployerOrDeductorOrCollectName": data.salary_income.employer_name if data.salary_income and hasattr(data.salary_income, "employer_name") else "",
                            "AmtCarriedToScheduleTDS1": _int(r.tds_tcs_advance_tax),
                        }
                    ] if data.salary_income else [],
                    "TotalTDSonSalaries": _int(r.tds_tcs_advance_tax),
                },
                "TaxesPaid": {
                    "TotalTaxesPaid": _int(r.tds_tcs_advance_tax),
                    "BalTaxPayable": max(0, _int(r.net_payable_refundable)),
                },
                "Refund": {
                    "RefundDue": max(0, -_int(r.net_payable_refundable)),
                },
                "Verification": {
                    "Declaration": {
                        "AssesseeVerName": profile.name,
                        "FatherName": "",
                        "AssesseeVerPAN": profile.pan,
                        "Place": "",
                        "Date": "",
                    }
                },
            }
        }
    }


def map_to_official_itr2(
    data: ExtractedTaxData,
    computation: TaxComputation,
    profile: FilerProfile,
) -> dict[str, Any]:
    """
    Produce ITR-2 JSON conforming to the IT Dept AY 2026-27 offline utility schema.
    ZERO LLM. Every field mapped from validated model objects.

    Top-level envelope:  { "ITR": { "ITR2": { ... } } }
    """
    from inditr.engine.capital_gains import aggregate_gains
    from inditr.models.tax_data import GainType, AssetType

    rec = computation.recommended_regime
    r = computation.new_regime if rec == "new" else computation.old_regime

    gross_salary = _int(data.salary_income.gross_salary) if data.salary_income else 0
    std_ded = 75_000 if rec == "new" else 50_000
    net_salary = max(0, gross_salary - std_ded)

    age = _age_from_profile(profile)
    d = data.deductions
    from inditr.engine.deductions import compute_total_deductions
    sal = data.salary_income
    employer_nps = _int(sal.employer_nps_80ccd2) if sal else 0
    professional_tax = _int(sal.professional_tax) if sal else 0
    total_ded = _int(
        compute_total_deductions(
            d, rec, age=age,
            employer_nps_80ccd2=employer_nps,
            professional_tax=professional_tax,
        )
    )

    _EQUITY_TYPES = {AssetType.EQUITY, AssetType.EQUITY_MF}
    cg_summary = aggregate_gains(data.capital_gains)

    stcg_111a = _int(cg_summary["stcg_equity_total"])
    ltcg_112a = _int(cg_summary["ltcg_equity_total"])
    ltcg_property = _int(cg_summary["ltcg_property_total"])
    slab_cg = _int(cg_summary["slab_cg_total"])
    cg_tax = _int(
        cg_summary["stcg_111a_tax"]
        + cg_summary["ltcg_112a_tax"]
        + cg_summary["ltcg_property_tax"]
        + cg_summary["ltcg_other_tax"]
    )

    # Build per-transaction CG schedule entries (department format)
    cg_entries_111a = []
    cg_entries_112a = []
    for g in data.capital_gains:
        is_equity = g.asset_type in _EQUITY_TYPES
        entry = {
            "SaleValue": _int(g.sale_value) if hasattr(g, "sale_value") else 0,
            "CostOfAcquisition": _int(g.cost_of_acquisition) if hasattr(g, "cost_of_acquisition") else 0,
            "FairMktValueOfCapAsset": 0,
            "CapGain": _int(g.gain_amount),
        }
        if is_equity and g.gain_type == GainType.STCG:
            cg_entries_111a.append(entry)
        elif is_equity and g.gain_type == GainType.LTCG:
            cg_entries_112a.append(entry)

    return {
        "ITR": {
            "ITR2": {
                "CreationInfo": {
                    "SWVersionNo": "1.0",
                    "SWCreatedBy": "IndITR",
                    "JSONCreatedBy": "IndITR",
                    "JSONCreationDate": __import__("datetime").date.today().strftime("%d/%m/%Y"),
                    "InterfaceCode": "O",
                    "XMLtoJSONVersionNo": "V1.0.1",
                },
                "Form_ITR2": {
                    "FormName": "ITR-2",
                    "Description": "For individuals/HUFs not having income from business or profession",
                    "AssessmentYear": "2026-27",
                    "SchemaVer": "Ver1.0",
                    "FormVer": "Ver1.0",
                },
                "PartA_GEN1": {
                    "PersonalInfo": {
                        "AsseseeeName": profile.name,
                        "PAN": profile.pan,
                        "DOB": _dob_fmt(profile.date_of_birth),
                        "AadhaarCardNo": "",
                        "ResidentialStatus": "RES",
                        "FilingStatus": {
                            "ReturnFileSec": "11",
                            "OptOutNewTaxRegime": "N" if rec == "new" else "Y",
                        },
                    },
                },
                "ScheduleS": {
                    "Salaries": [{
                        "NameOfEmployer": data.salary_income.employer_name if data.salary_income and hasattr(data.salary_income, "employer_name") else "",
                        "TANofEmployer": data.salary_income.employer_tan if data.salary_income and hasattr(data.salary_income, "employer_tan") else "",
                        "GrossSalary": gross_salary,
                        "Salary": gross_salary,
                        "ValueOfPerquisites": 0,
                        "ProfitInLieuOfSalary": 0,
                        "AllwncExemptUs10": 0,
                        "NetSalary": net_salary,
                        "DeductionUs16": std_ded,
                        "ProfessionalTax": professional_tax,
                        "EntertainmentAlw": 0,
                        "IncomeFromSal": max(0, gross_salary - std_ded - professional_tax),
                    }] if data.salary_income else [],
                    "TotalIncomeOfHP": _int(data.house_property_income),
                },
                "ScheduleHP": {
                    "TotalIncomeChargeableUnHP": _int(data.house_property_income),
                },
                "ScheduleCG": {
                    "ShortTermCapGain15Per": {
                        "NRITransacSec48Dtail": [],
                        "EquityMFonSTT": cg_entries_111a,
                        "TotalAmtDtOfSlumpSale": 0,
                        "TotalSTCG": stcg_111a,
                    },
                    "LongTermCapGain10Per": {
                        "Proviso112Applicable": "N",
                        "NRISecur112Applicable": "N",
                        "SaleValueofAsset": 0,
                        "FairMktValueofAsset": 0,
                        "CostOfAcquisition": 0,
                        "CapGainsWithoutIndex": ltcg_112a,
                        "TotalLTCG": ltcg_112a,
                    },
                    "LongTermCapGain20Per": {
                        "TotalLTCG": ltcg_property,
                    },
                    "LTCGonImmovblProp": {
                        "TotalLTCGonImmovblProp": ltcg_property,
                    },
                    "TotalCapGains": stcg_111a + ltcg_112a + ltcg_property + _int(cg_summary["ltcg_other_total"]) + slab_cg,
                },
                "ScheduleOS": {
                    "IncOthThanOwnRaceHorse": _int(data.other_income),
                    "TotIncFromOS": _int(data.other_income),
                },
                "ScheduleVIA": {
                    "UsrDeductUndChapVIA": {
                        "Section80C": _int(d.sec_80c) if rec == "old" else 0,
                        "Section80CCDEmployer": employer_nps,
                        "Section80CCDO": _int(d.sec_80ccd_1b) if rec == "old" else 0,
                        "Section80D": _int(d.sec_80d) if rec == "old" else 0,
                        "Section80E": _int(d.sec_80e) if rec == "old" else 0,
                        "Section80G": _int(d.sec_80g) if rec == "old" else 0,
                        "Section80TTA": _int(d.sec_80tta) if rec == "old" else 0,
                        "Section80TTB": _int(d.sec_80ttb) if rec == "old" else 0,
                        "TotalChapVIADeductions": total_ded,
                    }
                },
                "PartBTI": {
                    "TotalIncome": _int(r.taxable_income),
                    "GrossTotalIncome": _int(r.gross_income),
                    "TotalDeductions": total_ded,
                },
                "PartB_TTI": {
                    "TaxPayableOnTI": _int(r.income_tax),
                    "TaxPayableAfterRebate": max(0, _int(r.income_tax) + cg_tax - _int(r.rebate_87a)),
                    "TotalSurcharge": _int(r.surcharge),
                    "EducationCess": _int(r.health_education_cess),
                    "GrossTaxLiability": _int(r.total_tax_liability),
                    "TaxReliefUs89": 0,
                    "NetTaxLiability": _int(r.total_tax_liability),
                    "TotalTaxPayable": _int(r.total_tax_liability),
                    "TaxesPaid": {
                        "TotalTaxesPaid": _int(r.tds_tcs_advance_tax),
                        "BalTaxPayable": max(0, _int(r.net_payable_refundable)),
                    },
                    "Refund": {
                        "RefundDue": max(0, -_int(r.net_payable_refundable)),
                    },
                },
                "ScheduleTDS1": {
                    "TDSSalaryDeductor": [
                        {
                            "EmployerOrDeductorOrCollectTAN": getattr(sal, "employer_tan", ""),
                            "EmployerOrDeductorOrCollectName": getattr(sal, "employer_name", ""),
                            "AmtCarriedToScheduleTDS1": _int(r.tds_tcs_advance_tax),
                        }
                    ] if sal else [],
                    "TotalTDSonSalaries": _int(r.tds_tcs_advance_tax),
                },
                "Verification": {
                    "Declaration": {
                        "AssesseeVerName": profile.name,
                        "FatherName": "",
                        "AssesseeVerPAN": profile.pan,
                        "Place": "",
                        "Date": "",
                    }
                },
            }
        }
    }
