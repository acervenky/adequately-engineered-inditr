"""
LLM tool definitions for IndITR conversational nodes.

These tools wrap the real tax engine so the LLM can fetch accurate numbers
instead of computing them itself.  Every tool handler returns a plain dict
that is JSON-serialised and fed back to the LLM as a tool-result message.

Tools exposed:
  calculate             — safe Python eval for any arithmetic expression
  estimate_tax          — run engine on provided salary + CG + deductions
  calculate_hra         — compute HRA exemption (Section 10(13A))
  check_87a_rebate      — explain 87A eligibility given income + CG
  deduction_impact      — show how a new 80C/80D/NPS deduction changes tax
"""
from __future__ import annotations
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Tool schemas (OpenAI function-calling format) ─────────────────────────────

TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": (
                "Safe Python evaluator for UNIT CONVERSIONS and AGGREGATIONS only. "
                "Use ONLY to pre-process raw user inputs before passing to a tax tool — "
                "e.g. converting monthly salary to annual ('88888 * 12'), summing items "
                "('50000 + 30000 + 20000'), or checking a cap ('min(150000, 85000)'). "
                "DO NOT use this for: tax liability, tax saving, HRA exemption, 87A rebate, "
                "deduction impact, or ANY amount that has a dedicated tool. "
                "For those, always call estimate_tax / calculate_hra / check_87a_rebate / "
                "deduction_impact instead — they apply the correct legal rules."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "A valid Python arithmetic expression to evaluate",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estimate_tax",
            "description": (
                "PRIMARY tool — compute income tax using the certified legal engine. "
                "Call this for ANY tax-related number: liability, payable, refund, regime "
                "comparison, or savings. The engine applies slabs, standard deduction, "
                "surcharge, 4% health+education cess, 87A rebate, and CG special rates "
                "correctly. NEVER use 'calculate' for tax amounts — it applies flat rates "
                "and will give a wrong answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "gross_salary": {
                        "type": "number",
                        "description": "Annual gross salary in INR (0 if not salaried)"
                    },
                    "date_of_birth": {
                        "type": "string",
                        "description": "Date of birth in YYYY-MM-DD format (used for slab selection)"
                    },
                    "sec_80c": {
                        "type": "number",
                        "description": "Section 80C investments (PPF, ELSS, LIC, PF) — max 150000"
                    },
                    "sec_80d": {
                        "type": "number",
                        "description": "Section 80D health insurance premium"
                    },
                    "sec_80ccd_1b": {
                        "type": "number",
                        "description": "Section 80CCD(1B) employee NPS contribution — max 50000"
                    },
                    "hra_exemption": {
                        "type": "number",
                        "description": "HRA exemption under Section 10(13A) — 0 if not applicable"
                    },
                    "stcg_equity": {
                        "type": "number",
                        "description": "Short-term capital gains on equity/equity-MF (Section 111A, taxed at 20%)"
                    },
                    "ltcg_equity": {
                        "type": "number",
                        "description": "Long-term capital gains on equity/equity-MF (Section 112A, taxed at 12.5% after 1.25L exemption)"
                    },
                    "other_income": {
                        "type": "number",
                        "description": "Other income (freelance, interest, dividends)"
                    },
                    "house_property_income": {
                        "type": "number",
                        "description": "Net house property income (negative = loss, capped at -200000 under old regime)"
                    },
                    "sec_80e": {
                        "type": "number",
                        "description": "Section 80E education loan interest (no cap, old regime only)"
                    },
                    "sec_80g": {
                        "type": "number",
                        "description": "Section 80G donations — net eligible amount after 50%/100% and GTI cap"
                    },
                    "sec_54ec_exemption": {
                        "type": "number",
                        "description": "Section 54EC reinvestment in NHAI/REC bonds — max 5000000 (₹50L)"
                    },
                    "home_loan_interest": {
                        "type": "number",
                        "description": "Section 24b home loan interest on self-occupied property — max 200000 (₹2L)"
                    },
                },
                "required": ["gross_salary", "date_of_birth"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_hra",
            "description": (
                "Compute HRA exemption under Section 10(13A). "
                "Call this when user mentions rent paid but no HRA received from employer. "
                "Also explains Section 80GG if user gets no HRA component."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "basic_salary": {
                        "type": "number",
                        "description": "Annual basic salary (or gross if basic unknown)"
                    },
                    "hra_received": {
                        "type": "number",
                        "description": "Annual HRA received from employer (0 if not in salary)"
                    },
                    "rent_paid_annual": {
                        "type": "number",
                        "description": "Annual rent paid by employee"
                    },
                    "city_type": {
                        "type": "string",
                        "enum": ["metro", "non_metro"],
                        "description": "metro = Mumbai/Delhi/Kolkata/Chennai; non_metro = all others"
                    },
                },
                "required": ["basic_salary", "hra_received", "rent_paid_annual", "city_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_87a_rebate",
            "description": (
                "Explain Section 87A rebate eligibility and amount for AY 2026-27. "
                "Important: rebate does NOT apply to STCG (111A) or LTCG (112A) tax. "
                "Call this when user asks about zero-tax limit or 12L rebate."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "total_income": {
                        "type": "number",
                        "description": "Total taxable income including CG"
                    },
                    "regime": {
                        "type": "string",
                        "enum": ["old", "new"],
                        "description": "Tax regime to check rebate for"
                    },
                    "stcg_equity": {
                        "type": "number",
                        "description": "STCG on equity (111A) — rebate excluded on this"
                    },
                    "ltcg_equity": {
                        "type": "number",
                        "description": "LTCG on equity (112A) — rebate excluded on this"
                    },
                },
                "required": ["total_income", "regime"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deduction_impact",
            "description": (
                "Show how investing a specific amount in a deduction (80C, 80D, NPS 80CCD1B) "
                "changes total tax under old regime. Useful for tax-saving tips. "
                "Returns tax before and after, and net saving."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "gross_salary": {"type": "number"},
                    "date_of_birth": {"type": "string"},
                    "current_80c": {"type": "number", "description": "Current 80C invested"},
                    "additional_80c": {"type": "number", "description": "Additional 80C being considered"},
                    "current_80d": {"type": "number", "description": "Current 80D"},
                    "additional_80d": {"type": "number", "description": "Additional 80D being considered"},
                    "current_nps": {"type": "number", "description": "Current 80CCD(1B) NPS"},
                    "additional_nps": {"type": "number", "description": "Additional NPS being considered"},
                    "stcg_equity": {"type": "number"},
                    "ltcg_equity": {"type": "number"},
                },
                "required": ["gross_salary", "date_of_birth"],
            },
        },
    },
]


# ── Tool handler implementations ──────────────────────────────────────────────

def _fmt(n: float) -> str:
    """Format number as INR with commas."""
    return f"₹{n:,.0f}"


def _run_engine(
    gross_salary: float,
    dob: str,
    sec_80c: float = 0,
    sec_80d: float = 0,
    sec_80ccd_1b: float = 0,
    hra_exemption: float = 0,
    stcg_equity: float = 0,
    ltcg_equity: float = 0,
    other_income: float = 0,
    house_property_income: float = 0,
    sec_80e: float = 0,
    sec_80g: float = 0,
    sec_54ec_exemption: float = 0,
    home_loan_interest: float = 0,
) -> dict:
    """Run compare_regimes() and return a clean result dict."""
    from inditr.models.tax_data import (
        ExtractedTaxData, SalaryIncome, Deductions, CapitalGain, GainType, AssetType
    )
    from inditr.models.profile import FilerProfile, EmploymentType
    from inditr.engine.regime import compare_regimes

    salary = SalaryIncome(gross_salary=gross_salary)
    deductions = Deductions(
        sec_80c=min(sec_80c, 150_000),
        sec_80d=sec_80d,
        sec_80ccd_1b=min(sec_80ccd_1b, 50_000),
        hra_exemption=hra_exemption,          # FIXED: belongs on Deductions, not SalaryIncome
        sec_80e=sec_80e,
        sec_80g=sec_80g,
        sec_54ec_exemption=min(sec_54ec_exemption, 5_000_000),
        home_loan_interest=home_loan_interest,
    )
    cg_list: list[CapitalGain] = []
    if stcg_equity:
        cg_list.append(CapitalGain(
            gain_type=GainType.STCG,
            asset_type=AssetType.EQUITY,
            sale_value=stcg_equity,
            cost_of_acquisition=0,
            gain_amount=stcg_equity,
            section_112a=False,
        ))
    if ltcg_equity:
        cg_list.append(CapitalGain(
            gain_type=GainType.LTCG,
            asset_type=AssetType.EQUITY,
            sale_value=ltcg_equity,
            cost_of_acquisition=0,
            gain_amount=ltcg_equity,
            section_112a=True,
        ))

    data = ExtractedTaxData(
        salary_income=salary,
        capital_gains=cg_list,
        other_income=other_income,
        house_property_income=house_property_income,
        deductions=deductions,
    )
    profile = FilerProfile(
        name="Filer",
        pan="ABCDE0000A",   # dummy — doesn't affect computation
        date_of_birth=dob,
        employment_type=EmploymentType.SALARIED,
    )
    comp = compare_regimes(data, profile)
    old = comp.old_regime
    new = comp.new_regime
    return {
        "old_regime": {
            "gross_income": _fmt(old.gross_income),
            "total_deductions": _fmt(old.total_deductions),
            "taxable_income": _fmt(old.taxable_income),
            "income_tax": _fmt(old.income_tax),
            "surcharge": _fmt(old.surcharge),
            "cess": _fmt(old.health_education_cess),
            "rebate_87a": _fmt(old.rebate_87a),
            "total_tax_liability": _fmt(old.total_tax_liability),
            "net_payable_refundable": _fmt(old.net_payable_refundable),
        },
        "new_regime": {
            "gross_income": _fmt(new.gross_income),
            "total_deductions": _fmt(new.total_deductions),
            "taxable_income": _fmt(new.taxable_income),
            "income_tax": _fmt(new.income_tax),
            "surcharge": _fmt(new.surcharge),
            "cess": _fmt(new.health_education_cess),
            "rebate_87a": _fmt(new.rebate_87a),
            "total_tax_liability": _fmt(new.total_tax_liability),
            "net_payable_refundable": _fmt(new.net_payable_refundable),
        },
        "recommended_regime": comp.recommended_regime,
        "savings": _fmt(comp.savings_from_recommendation),
        "reason": comp.recommendation_reason,
        # Raw numerics used internally by handle_deduction_impact (not shown to LLM)
        "_raw_old_tax": float(old.total_tax_liability),
        "_raw_new_tax": float(new.total_tax_liability),
    }


def handle_calculate(args: dict) -> dict:
    """Safe arithmetic evaluator — only math builtins, no imports or side effects."""
    import math
    expr = str(args.get("expression", "")).strip()
    if not expr:
        return {"error": "Empty expression"}

    # Defense-in-depth: block dunder access and dangerous builtins.
    # The eval sandbox already uses {"__builtins__": {}} but an explicit
    # check gives a clearer error and prevents creative bypass attempts.
    _BLOCKED = ("__", "getattr", "setattr", "import", "open", "exec", "eval", "compile")
    if any(kw in expr for kw in _BLOCKED):
        return {"error": "Expression contains disallowed keyword"}

    # Allowlist: digits, operators, whitespace, parens, dots, commas, and safe names
    _SAFE_NAMES = {
        "round": round, "min": min, "max": max, "abs": abs, "sum": sum,
        "int": int, "float": float, "pow": pow,
        "sqrt": math.sqrt, "ceil": math.ceil, "floor": math.floor,
        "log": math.log, "log10": math.log10,
        "pi": math.pi, "e": math.e,
        # Common Indian finance shorthands
        "lakh": 100_000, "crore": 10_000_000,
    }
    try:
        result = eval(expr, {"__builtins__": {}}, _SAFE_NAMES)  # noqa: S307
        # Format nicely if it's a number
        if isinstance(result, (int, float)):
            formatted = f"{result:,.2f}".rstrip("0").rstrip(".")
            return {
                "expression": expr,
                "result": result,
                "formatted": formatted,
            }
        return {"expression": expr, "result": str(result)}
    except Exception as e:
        return {"error": f"Could not evaluate '{expr}': {e}"}


def handle_estimate_tax(args: dict) -> dict:
    try:
        return _run_engine(
            gross_salary=float(args.get("gross_salary", 0)),
            dob=args.get("date_of_birth", "1990-01-01"),
            sec_80c=float(args.get("sec_80c", 0)),
            sec_80d=float(args.get("sec_80d", 0)),
            sec_80ccd_1b=float(args.get("sec_80ccd_1b", 0)),
            hra_exemption=float(args.get("hra_exemption", 0)),
            stcg_equity=float(args.get("stcg_equity", 0)),
            ltcg_equity=float(args.get("ltcg_equity", 0)),
            other_income=float(args.get("other_income", 0)),
            house_property_income=float(args.get("house_property_income", 0)),
            sec_80e=float(args.get("sec_80e", 0)),
            sec_80g=float(args.get("sec_80g", 0)),
            sec_54ec_exemption=float(args.get("sec_54ec_exemption", 0)),
            home_loan_interest=float(args.get("home_loan_interest", 0)),
        )
    except Exception as e:
        return {"error": str(e)}


def handle_calculate_hra(args: dict) -> dict:
    try:
        basic = float(args["basic_salary"])
        hra_recv = float(args["hra_received"])
        rent = float(args["rent_paid_annual"])
        metro = args.get("city_type", "non_metro") == "metro"

        if hra_recv <= 0:
            # No HRA component — check Section 80GG instead
            # 80GG: least of (i) ₹5000/month, (ii) 25% of total income, (iii) rent - 10% income
            # We use gross_salary as a proxy for total income here
            monthly_80gg = min(5_000, basic * 0.25 / 12, max(0, rent / 12 - basic * 0.10 / 12))
            annual_80gg = monthly_80gg * 12
            return {
                "hra_exemption": 0,
                "note": (
                    "No HRA in salary. You may claim Section 80GG instead "
                    f"(estimated {_fmt(annual_80gg)}/yr). "
                    "80GG is only available under the old regime and requires Form 10BA."
                ),
                "sec_80gg_estimate": round(annual_80gg, 2),
            }

        # Section 10(13A): least of:
        # (i)  actual HRA received
        # (ii) rent paid - 10% of basic
        # (iii) 50% of basic (metro) or 40% of basic (non-metro)
        actual = hra_recv
        excess_rent = max(0, rent - 0.10 * basic)
        city_pct = 0.50 if metro else 0.40
        exemption = min(actual, excess_rent, city_pct * basic)

        return {
            "hra_received": _fmt(hra_recv),
            "actual_hra": _fmt(actual),
            "rent_minus_10pct_basic": _fmt(excess_rent),
            "city_pct_of_basic": _fmt(city_pct * basic),
            "hra_exemption": round(exemption, 2),
            "hra_exemption_fmt": _fmt(exemption),
            "taxable_hra": _fmt(hra_recv - exemption),
            "note": (
                "HRA exemption = minimum of the three limits above. "
                "Only available under old regime."
            ),
        }
    except Exception as e:
        return {"error": str(e)}


def handle_check_87a_rebate(args: dict) -> dict:
    try:
        total_income = float(args["total_income"])
        regime = args.get("regime", "new")
        stcg = float(args.get("stcg_equity", 0))
        ltcg = float(args.get("ltcg_equity", 0))
        special_rate_income = stcg + max(0, ltcg - 125_000)  # LTCG exempt slab

        if regime == "new":
            threshold = 1_200_000
            max_rebate = 60_000
            eligible = total_income <= threshold
        else:
            threshold = 500_000
            max_rebate = 12_500
            eligible = total_income <= threshold

        result: dict[str, Any] = {
            "regime": regime,
            "total_income": _fmt(total_income),
            "threshold": _fmt(threshold),
            "eligible_for_rebate": eligible,
            "max_rebate": _fmt(max_rebate),
        }

        if eligible and special_rate_income > 0:
            result["important_caveat"] = (
                f"87A rebate of up to {_fmt(max_rebate)} applies ONLY to slab-rate income. "
                f"Tax on STCG ({_fmt(stcg)} at 20%) and LTCG above ₹1.25L ({_fmt(max(0, ltcg-125_000))} at 12.5%) "
                f"is NOT reduced by the rebate — Budget 2025 clarification."
            )
            result["net_effect"] = (
                "Your salary tax can be zeroed by 87A, but you still owe capital gains tax."
            )
        elif eligible:
            result["net_effect"] = (
                f"Great news — your salary tax is fully covered by the 87A rebate "
                f"(up to {_fmt(max_rebate)}). Effective tax ≈ ₹0 on salary income."
            )
        else:
            over = total_income - threshold
            result["net_effect"] = (
                f"Income exceeds the {_fmt(threshold)} threshold by {_fmt(over)}. "
                f"No 87A rebate available."
            )

        return result
    except Exception as e:
        return {"error": str(e)}


def handle_deduction_impact(args: dict) -> dict:
    try:
        base_args = {
            "gross_salary": float(args["gross_salary"]),
            "dob": args.get("date_of_birth", "1990-01-01"),
            "sec_80c": float(args.get("current_80c", 0)),
            "sec_80d": float(args.get("current_80d", 0)),
            "sec_80ccd_1b": float(args.get("current_nps", 0)),
            "stcg_equity": float(args.get("stcg_equity", 0)),
            "ltcg_equity": float(args.get("ltcg_equity", 0)),
        }
        new_args = base_args.copy()
        new_args["sec_80c"] = min(
            float(args.get("current_80c", 0)) + float(args.get("additional_80c", 0)),
            150_000,
        )
        new_args["sec_80d"] = float(args.get("current_80d", 0)) + float(args.get("additional_80d", 0))
        new_args["sec_80ccd_1b"] = min(
            float(args.get("current_nps", 0)) + float(args.get("additional_nps", 0)),
            50_000,
        )

        before = _run_engine(**base_args)
        after = _run_engine(**new_args)

        saving_old = before["_raw_old_tax"] - after["_raw_old_tax"]

        return {
            "before": {
                "old_regime_tax": before["old_regime"]["total_tax_liability"],
                "new_regime_tax": before["new_regime"]["total_tax_liability"],
            },
            "after": {
                "old_regime_tax": after["old_regime"]["total_tax_liability"],
                "new_regime_tax": after["new_regime"]["total_tax_liability"],
            },
            "old_regime_saving_amount": round(saving_old, 2),
            "old_regime_saving": (
                f"{before['old_regime']['total_tax_liability']} → "
                f"{after['old_regime']['total_tax_liability']} "
                f"(saving {_fmt(saving_old)})"
            ),
            "note": (
                "Additional deductions only reduce tax under the old regime. "
                "New regime tax is unaffected by 80C/80D/NPS."
            ),
        }
    except Exception as e:
        return {"error": str(e)}


# ── Dispatch ──────────────────────────────────────────────────────────────────

_HANDLERS = {
    "calculate":         handle_calculate,
    "estimate_tax":      handle_estimate_tax,
    "calculate_hra":     handle_calculate_hra,
    "check_87a_rebate":  handle_check_87a_rebate,
    "deduction_impact":  handle_deduction_impact,
}


def execute_tool(name: str, args: dict) -> str:
    """Execute a tool by name and return JSON-encoded result string."""
    handler = _HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = handler(args)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return json.dumps({"error": str(e)})


def run_tool_loop(
    model: str,
    messages: list[dict],
    system_prompt: str,
    max_rounds: int = 5,
) -> tuple[str, list[dict]]:
    """
    Run a tool-calling conversation loop.

    Sends messages to the LLM with TOOL_SCHEMAS attached.  If the model
    returns tool_calls, executes each tool and feeds the results back.
    Repeats until the model returns a plain text reply (no tool calls) or
    max_rounds is reached.

    Returns:
        (final_text_reply, updated_messages_list)
    """
    import litellm

    # Check whether the configured model supports function/tool calling.
    # Many local models (7B quants, older checkpoints) don't implement tool_calls.
    # Falling back to a plain completion avoids a hard 400/422 error at runtime.
    _supports_tools = True
    try:
        _supports_tools = litellm.supports_function_calling(model=model)
    except Exception:
        pass  # litellm may not know the model — assume yes and let the call fail naturally

    if not _supports_tools:
        _plain_msgs = [{"role": "system", "content": system_prompt}] + messages
        _resp = litellm.completion(
            model=model,
            messages=_plain_msgs,
            temperature=0.3,
            max_tokens=1024,
        )
        return (_resp.choices[0].message.content or ""), _plain_msgs

    # Prepend a hard tool-priority rule so the LLM never confuses the tools.
    _TOOL_PRIORITY = (
        "\n\nTOOL USAGE RULES (follow strictly):\n"
        "1. For ANY tax amount (liability, payable, saving, regime comparison) → estimate_tax\n"
        "2. For HRA exemption → calculate_hra\n"
        "3. For 87A rebate eligibility → check_87a_rebate\n"
        "4. For impact of adding 80C/80D/NPS → deduction_impact\n"
        "5. For unit conversion or summing user inputs ONLY → calculate\n"
        "NEVER use 'calculate' to compute a tax amount — it applies flat rates "
        "and will give legally incorrect results."
    )
    full_messages = [{"role": "system", "content": system_prompt + _TOOL_PRIORITY}] + messages

    for _ in range(max_rounds):
        response = litellm.completion(
            model=model,
            messages=full_messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.3,
            max_tokens=1024,
        )
        msg = response.choices[0].message

        # No tool calls -> plain reply, we're done
        if not msg.tool_calls:
            return (msg.content or ""), full_messages

        # Append assistant message with tool_calls
        full_messages.append(msg.model_dump(exclude_none=True))

        # Execute each tool and append results
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except Exception:
                args = {}
            result_str = execute_tool(tc.function.name, args)
            logger.info("Tool %s called -> %s", tc.function.name, result_str[:200])
            full_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str,
            })

    # Exhausted rounds -- ask for a summary without tools
    response = litellm.completion(
        model=model,
        messages=full_messages,
        temperature=0.3,
        max_tokens=512,
    )
    return (response.choices[0].message.content or ""), full_messages
