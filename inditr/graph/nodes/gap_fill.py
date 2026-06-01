"""
Act 3 — Gap fill and cross-check nodes.
gap_fill_chat uses LLM.
cross_check and aggregate_data are pure Python (no LLM).
"""
from __future__ import annotations
from typing import Any

from inditr.models.state import TaxFilingState


def _vda_note(mentions_vda: bool) -> str:
    if not mentions_vda:
        return ""
    return (
        "\nIMPORTANT — VDA/CRYPTO INCOME: The user has mentioned cryptocurrency or VDA. "
        "Ask explicitly: (1) Did they sell/trade any crypto, NFTs, or VDA during FY 2025-26? "
        "(2) What is the total gain (sale price − purchase price) across all trades? "
        "(3) Did they receive any crypto as airdrop, staking reward, or gift? "
        "CRITICAL RULES TO CONVEY: VDA gains are taxed at 30% flat regardless of holding period. "
        "Losses in one crypto CANNOT be set off against gains in another. "
        "No deduction except cost of acquisition. "
        "TDS of 1% may already have been deducted by the exchange — check Form 26AS. "
        "Must file ITR-2 (not ITR-1) if any VDA income exists. "
        "Record answers as 'vda_gains_total': amount, 'vda_tds_credited': amount."
    )


def gap_fill_chat(state: TaxFilingState) -> dict[str, Any]:
    """
    LLM node: ask targeted questions about missing deductions, HRA, investments.
    Has access to tax computation tools so it never needs to guess numbers.
    """
    import json
    import re
    from inditr.graph.llm import MODEL
    from inditr.graph.tools import run_tool_loop

    messages = list(state.get("messages", []))
    errors = list(state.get("errors", []))
    documents = state.get("documents", [])

    # Build summary of what we have
    extracted_fields = set()
    for doc in documents:
        extracted_fields.update(doc.get("fields", {}).keys())

    # Detect whether any mutual fund trades are present so we can ask a targeted
    # debt-MF question.  We check the raw parsed gain dicts — not the processed
    # CapitalGain objects — because aggregate_data hasn't run yet at this point.
    has_mf_trades = False
    has_property_cg = False
    for doc in documents:
        cg_field = doc.get("fields", {}).get("capital_gains", {})
        if cg_field:
            for g in (cg_field.get("value") or []):
                at = str(g.get("asset_type", "")).lower()
                if at in ("equity_mf", "debt_mf"):
                    has_mf_trades = True
                if at == "immovable_property":
                    has_property_cg = True
        if has_mf_trades and has_property_cg:
            break

    # Also check for VDA/crypto income signals in messages
    all_msg_text = " ".join(m.get("content", "") for m in messages).lower()
    mentions_vda = any(kw in all_msg_text for kw in (
        "crypto", "bitcoin", "ethereum", "nft", "vda", "binance",
        "coinswitch", "wazirx", "coindcx", "polygon", "solana", "usdt",
    ))

    mf_debt_note = (
        "\nIMPORTANT — MUTUAL FUND DEBT CLASSIFICATION: Mutual fund trades are present. "
        "Ask the user whether any of their MF schemes are debt funds (e.g. liquid funds, "
        "overnight funds, bond funds, gilt funds, FMPs, or any fund with 'duration', "
        "'credit risk', 'banking & PSU', or 'corporate bond' in the name). "
        "Debt MF gains post-Apr-2023 are taxed at the user's slab rate — NOT at the "
        "equity MF rate of 12.5%/20%. Record the answer as 'has_debt_mf': true/false."
        if has_mf_trades else ""
    )

    property_cg_note = (
        "\nIMPORTANT — PROPERTY CAPITAL GAINS REINVESTMENT: Property/immovable asset gains are present. "
        "ALWAYS ask the user whether they have reinvested or plan to reinvest the sale proceeds, as this can reduce or eliminate their CG tax:\n"
        "• Section 54: Sold a residential house? If you buy/construct another house within 2/3 years, the LTCG is fully or partially exempt.\n"
        "• Section 54EC: Sold any property? Invest up to ₹50L in NHAI or REC infrastructure bonds within 6 months to claim exemption.\n"
        "• Section 54F: Sold non-residential property (commercial, land, gold)? Reinvest full net sale consideration in a residential house for full LTCG exemption.\n"
        "Collect: (a) type of property sold (residential or non-residential), "
        "(b) whether they have purchased/are constructing a new house, "
        "(c) whether they have invested or plan to invest in 54EC bonds. "
        "Record the exempt amounts as: 'sec_54_exemption': amount, 'sec_54ec_exemption': amount, 'sec_54f_exemption': amount."
        if has_property_cg else ""
    )

    # RAG: pull relevant deduction rules for the current conversation
    last_user_msg = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"),
        "deductions 80C 80D HRA NPS",
    )
    rag_context = ""
    try:
        from inditr.rag.retriever import retrieve
        rag_context = retrieve(last_user_msg, topk=3)
    except Exception:
        pass

    rag_block = (
        f"\n\nRELEVANT TAX RULES (use these; do not contradict):\n{rag_context}"
        if rag_context else ""
    )

    system_prompt = (
        "You are IndITR, a friendly Indian tax assistant. Your ONLY job right now is to "
        "collect missing deduction and income details from the user — NOT to compute tax. "
        "The tax computation will be done separately by a certified engine after you finish. "
        "Do NOT calculate, estimate, or show tax amounts, regimes, or summaries. "
        "Do NOT produce markdown tables, tax breakdowns, or comparisons. "
        "ONLY ask short, friendly questions to collect: "
        "80C investments (PPF/ELSS/LIC/PF, max ₹1.5L), "
        "80D health insurance premium (self/family/parents), "
        "HRA (if renting — monthly rent amount and city), "
        "home loan interest (Section 24b), "
        "education loan interest (80E — up to 8 years, no cap), "
        "NPS employee contributions (80CCD(1B), additional ₹50K beyond 80C), "
        "savings bank account interest (80TTA, up to ₹10K for non-seniors), "
        "donations to PM/CM relief fund or other approved institutions (80G). "
        "Ask one or two questions at a time. "
        "NEVER output JSON or code blocks in your conversational replies. "
        "When you have collected all needed information, output EXACTLY this sentinel alone "
        "on its own line: ##GAP_FILL_DONE## "
        "then on the next line a JSON object: "
        '{{"gap_fill_complete": true, "answers": {{"field": value}}}}'
        f"{mf_debt_note}"
        f"{property_cg_note}"
        f"{_vda_note(mentions_vda)}"
        f"{rag_block}"
    )

    def _strip_code_blocks(text: str) -> str:
        """Remove markdown code fences and raw JSON from a reply."""
        # Remove ```json ... ``` or ``` ... ``` blocks entirely
        text = re.sub(r'```[a-z]*\s*\{.*?\}\s*```', '', text, flags=re.DOTALL)
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        # Remove bare JSON objects that start with { and contain gap_fill_complete
        text = re.sub(r'\{[^{}]*"gap_fill_complete"[^{}]*\}', '', text, flags=re.DOTALL)
        return text.strip()

    def _try_extract_json(text: str) -> dict | None:
        """Try to extract gap-fill JSON from various LLM output formats."""
        # Strategy 1: sentinel ##GAP_FILL_DONE##
        if "##GAP_FILL_DONE##" in text:
            after = text.split("##GAP_FILL_DONE##", 1)[1].strip()
            try:
                return json.loads(after)
            except Exception:
                pass

        # Strategy 2: find a JSON object anywhere using brace-depth tracking
        depth = 0
        start = None
        for i, ch in enumerate(text):
            if ch == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0 and start is not None:
                    candidate = text[start:i + 1]
                    try:
                        data = json.loads(candidate)
                        if data.get("gap_fill_complete"):
                            return data
                    except Exception:
                        pass
                    start = None

        # Strategy 3: try parsing the whole reply
        try:
            data = json.loads(text.strip())
            if data.get("gap_fill_complete"):
                return data
        except Exception:
            pass

        return None

    try:
        # run_tool_loop handles tool calls transparently:
        # if model calls estimate_tax / check_87a_rebate etc., the real engine
        # runs and results are fed back — LLM never computes numbers itself.
        reply, _ = run_tool_loop(
            model=MODEL,
            messages=messages,
            system_prompt=system_prompt,
        )

        # Detect gap-fill completion signal (sentinel or JSON in reply)
        data = _try_extract_json(reply)
        if data and data.get("gap_fill_complete"):
            answers = data.get("answers", {})
            existing = state.get("gap_fill_answers", {}) or {}
            completion_msg = (
                "Thanks! I've got all the details I need. "
                "Let me now cross-check your data and prepare the tax computation..."
            )
            new_messages = messages + [{"role": "assistant", "content": completion_msg}]
            return {
                "gap_fill_answers": {**existing, **answers},
                "messages": new_messages,
                "current_act": "cross_check",
                "errors": errors,
            }

        # Conversational reply — strip any stray JSON/code blocks that slipped through
        clean_reply = _strip_code_blocks(reply)
        if not clean_reply:
            clean_reply = "Could you share a few more details so I can complete your tax filing?"

        new_messages = messages + [{"role": "assistant", "content": clean_reply}]
        return {
            "messages": new_messages,
            "current_act": "gap_fill_chat",
            "errors": errors,
        }

    except Exception as e:
        errors.append(f"LLM error in gap_fill_chat: {e}")
        return {
            "messages": messages,
            "current_act": "cross_check",
            "errors": errors,
        }


def cross_check(state: TaxFilingState) -> dict[str, Any]:
    """
    NO LLM — salary cross-check (±2% tolerance), capital gains directional check.
    Populates cross_check_results.
    """
    from inditr.models.outputs import CrossCheckResult

    documents = state.get("documents", [])
    errors = list(state.get("errors", []))
    results: list[dict] = []

    # Collect Form 16 gross salary
    form16_gross = None
    bank_salary_total = 0.0

    for doc in documents:
        doc_type = doc.get("doc_type", "")
        fields = doc.get("fields", {})

        if "form_16" in doc_type:
            gs_field = fields.get("gross_salary")
            if gs_field and gs_field.get("value") is not None:
                form16_gross = float(gs_field["value"])

        if "bank_statement" in doc_type:
            sal_field = fields.get("salary_credits")
            if sal_field and sal_field.get("value"):
                for credit in sal_field["value"]:
                    bank_salary_total += credit.get("amount", 0.0)

    # Salary cross-check
    if form16_gross is not None and bank_salary_total > 0:
        tolerance = abs(form16_gross - bank_salary_total) / form16_gross if form16_gross > 0 else 0
        if tolerance <= 0.02:
            results.append(CrossCheckResult(
                check="salary_form16_vs_bank",
                passed=True,
                severity="pass",
                message=f"Form 16 gross (₹{form16_gross:,.0f}) matches bank credits (₹{bank_salary_total:,.0f}) within 2%",
            ).model_dump())
        else:
            severity = "critical" if tolerance > 0.10 else "warning"
            results.append(CrossCheckResult(
                check="salary_form16_vs_bank",
                passed=False,
                severity=severity,
                message=f"Salary mismatch: Form 16 ₹{form16_gross:,.0f} vs bank ₹{bank_salary_total:,.0f} ({tolerance:.1%} difference)",
            ).model_dump())
    else:
        results.append(CrossCheckResult(
            check="salary_form16_vs_bank",
            passed=True,
            severity="pass",
            message="Salary cross-check skipped — insufficient data",
        ).model_dump())

    # Capital gains directional check
    cg_docs = [d for d in documents if "pnl" in d.get("doc_type", "") or "capital" in d.get("doc_type", "")]
    if cg_docs:
        for cg_doc in cg_docs:
            stcg_field = cg_doc.get("fields", {}).get("stcg_total")
            ltcg_field = cg_doc.get("fields", {}).get("ltcg_total")
            if stcg_field or ltcg_field:
                results.append(CrossCheckResult(
                    check="capital_gains_present",
                    passed=True,
                    severity="pass",
                    message=f"Capital gains data found in {cg_doc.get('doc_type', 'unknown')}",
                ).model_dump())

    # Check for critical failures
    critical_failures = [r for r in results if r.get("severity") == "critical"]

    # Critical failures → loop back to gap_fill_chat for user correction
    # Otherwise → aggregate and compute
    next_act = "gap_fill_chat" if critical_failures else "aggregate_data"
    return {
        "cross_check_results": results,
        "current_act": next_act,
        "errors": errors,
    }


def _parse_acquisition_date(date_str):
    """
    Parse a buy/entry date string from broker exports. Returns date or None.

    Handles:
      - ISO date strings: "2025-09-04"
      - openpyxl datetime-as-string: "2025-09-04 00:00:00" (date cells with time)
      - Indian formats: "04-09-2025", "04/09/2025", "04 Sep 2025", "04-Sep-2025"
      - datetime/date objects passed directly (e.g. from openpyxl read_only=False)
    """
    from datetime import datetime, date
    if date_str is None:
        return None
    # Handle actual date/datetime objects (openpyxl can return these)
    if isinstance(date_str, datetime):
        return date_str.date()
    if isinstance(date_str, date):
        return date_str
    if not isinstance(date_str, str):
        return None
    date_str = date_str.strip()
    if not date_str:
        return None
    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",   # openpyxl datetime stringified: "2025-09-04 00:00:00"
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d %b %Y",
        "%d-%b-%Y",
    ):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


# Mirror of zerodha._DEBT_MF_KEYWORDS — used as a backup classifier in aggregate_data.
# If the broker parser missed the classification (e.g. scheme_name was unavailable at
# parse time), we re-check here from the scrip name stored in the gain dict.
_DEBT_MF_KEYWORDS: frozenset[str] = frozenset({
    "liquid", "overnight", "money market",
    "ultra short", "low duration", "short duration", "medium duration",
    "long duration", "dynamic bond", "corporate bond", "credit risk",
    "banking and psu", "banking & psu", "gilt", "g-sec",
    "fixed maturity", "fmp", "floater", "floating rate",
    "debt fund", "debt index", "income fund", "treasury",
})


def aggregate_data(state: TaxFilingState) -> dict[str, Any]:
    """
    NO LLM — merge ParsedDocuments + gap_fill_answers into ExtractedTaxData.
    gap_fill values get source_document="user_input", confidence=1.0

    Form 16 field-name mapping (parser output → SalaryIncome / Deductions field):
      tds_deducted        → salary_income.tds_deducted   (Part B TDS; NOT added to tds_total)
      total_tds_deposited → salary_income.tds_deducted   (Part A fallback)
      deduction_80c       → deductions.sec_80c
      deduction_80d       → deductions.sec_80d
      deduction_80ccd1b   → deductions.sec_80ccd_1b
      deduction_80ccd2    → salary_income.employer_nps_80ccd2
    """
    from inditr.models.tax_data import (
        ExtractedTaxData, SalaryIncome, Deductions, CapitalGain, GainType, AssetType
    )

    documents = state.get("documents", [])
    gap_fill = state.get("gap_fill_answers", {}) or {}
    errors = list(state.get("errors", []))

    # ── Salary Income ─────────────────────────────────────────────────────────
    salary_data: dict = {}
    for doc in documents:
        if "form_16" in doc.get("doc_type", ""):
            fields = doc.get("fields", {})

            def _fv(key: str) -> float | None:
                """Read a numeric field value; returns None if absent/null."""
                f = fields.get(key)
                if f is not None and f.get("value") is not None:
                    try:
                        return float(f["value"])
                    except (TypeError, ValueError):
                        pass
                return None

            def _fs(key: str) -> str | None:
                f = fields.get(key)
                return str(f["value"]) if (f and f.get("value")) else None

            if (v := _fv("gross_salary")) is not None:
                salary_data["gross_salary"] = v
            if (v := _fv("basic_salary")) is not None:
                salary_data["basic"] = v
            if (v := _fv("hra_received")) is not None:
                salary_data["hra_received"] = v
            # hra_exemption from Form 16 Part B (employer-computed) — used as a baseline;
            # gap_fill can override with user's actual rent-based calculation.
            if (v := _fv("hra_exemption")) is not None:
                salary_data["hra_exemption"] = v
            if (v := _fv("professional_tax")) is not None:
                salary_data["professional_tax"] = v
            # 80CCD(2) employer NPS — Form 16 Part B field is "deduction_80ccd2"
            if (v := _fv("deduction_80ccd2")) is not None:
                salary_data["employer_nps_80ccd2"] = v
            # TDS: Form 16 parser writes Part B figure as "tds_deducted".
            # Fall back to Part A "total_tds_deposited" if Part B is missing.
            # NOTE: do NOT use "total_tds" — that key does not exist in the parser output.
            for tds_key in ("tds_deducted", "total_tds_deposited"):
                if (v := _fv(tds_key)) is not None:
                    salary_data["tds_deducted"] = v
                    break
            if (v := _fs("employer_name")) is not None:
                salary_data["employer_name"] = v
            if (v := _fs("employer_tan")) is not None:
                salary_data["employer_tan"] = v

    # gap_fill overrides (user_input confidence=1.0)
    if gap_fill.get("gross_salary"):
        salary_data["gross_salary"] = float(gap_fill["gross_salary"])
    if gap_fill.get("hra_received"):
        salary_data["hra_received"] = float(gap_fill["hra_received"])
    if gap_fill.get("hra_exemption"):
        salary_data["hra_exemption"] = float(gap_fill["hra_exemption"])

    salary_income = None
    if salary_data.get("gross_salary"):
        try:
            salary_income = SalaryIncome(**salary_data)
        except Exception as e:
            errors.append(f"SalaryIncome construction error: {e}")

    # ── Deductions ────────────────────────────────────────────────────────────
    deduction_data: dict = {}

    # From gap fill answers (user-declared, highest priority)
    _gap_deduction_fields = [
        "sec_80c", "sec_80d", "sec_80tta", "sec_80ccd_1b", "hra_exemption",
        "home_loan_interest",           # Section 24b
        "sec_80e",                      # Education loan interest
        "sec_80g",                      # Donations
        "sec_54_exemption",             # Sec 54 residential property reinvestment
        "sec_54ec_exemption",           # Sec 54EC NHAI/REC bonds
        "sec_54f_exemption",            # Sec 54F non-residential asset → residential
        "other_deductions",             # 80GG, 80U, etc.
    ]
    for f in _gap_deduction_fields:
        if gap_fill.get(f) is not None:
            try:
                deduction_data[f] = float(gap_fill[f])
            except (ValueError, TypeError):
                pass

    # From Form 16 Part B (lower priority than gap_fill — use setdefault)
    # Form 16 parser uses field names like "deduction_80c", not "sec_80c".
    _form16_deduction_map = {
        "deduction_80c":       "sec_80c",
        "deduction_80d":       "sec_80d",
        "deduction_80ccd1b":   "sec_80ccd_1b",
        "deduction_80e":       "sec_80e",       # Education loan interest — Form 16 Part B item (h)
        # deduction_80tta_ttb → 80TTA for non-seniors (validator will cap; senior case handled later)
        "deduction_80tta_ttb": "sec_80tta",
    }
    for doc in documents:
        if "form_16" in doc.get("doc_type", ""):
            fields = doc.get("fields", {})
            for f16_key, ded_key in _form16_deduction_map.items():
                f = fields.get(f16_key)
                if f is not None and f.get("value") is not None:
                    try:
                        deduction_data.setdefault(ded_key, float(f["value"]))
                    except (TypeError, ValueError):
                        pass

    try:
        deductions = Deductions(**deduction_data)
    except Exception as e:
        errors.append(f"Deductions construction error: {e}")
        deductions = Deductions()

    # ── Capital Gains ─────────────────────────────────────────────────────────
    capital_gains = []
    for doc in documents:
        cg_field = doc.get("fields", {}).get("capital_gains")
        if cg_field and cg_field.get("value"):
            for gain_dict in cg_field["value"]:
                # Skip intraday/speculation trades — they are business income
                # (slab-taxed under Schedule BP), NOT capital gains.  The
                # speculation_total warning below informs the user separately.
                if gain_dict.get("is_speculation"):
                    continue

                # Skip phantom entries from Zerodha's multi-section Tradewise sheet.
                # Each section boundary emits a repeated header row with scrip='Symbol',
                # isin='ISIN', gain_amount=0.  These are artefacts, not real trades.
                scrip_val = str(gain_dict.get("scrip") or "").strip()
                isin_val  = str(gain_dict.get("isin")  or "").strip()
                gain_val  = float(gain_dict.get("gain_amount", 0) or 0)
                if scrip_val == "Symbol" and isin_val in ("ISIN", "Entry Date", ""):
                    continue
                # Also skip section-name rows (Mutual Funds, F&O, etc.) with no ISIN
                if not isin_val and gain_val == 0:
                    continue

                try:
                    acquisition_date = _parse_acquisition_date(gain_dict.get("buy_date", ""))
                    asset_type = AssetType(gain_dict.get("asset_type", "other"))

                    # Backup debt-MF reclassification: if the parser had no scheme name at
                    # parse time it defaults to EQUITY_MF for all INF ISINs.  Re-check here
                    # using the scrip (scheme) name stored in the gain dict.
                    if asset_type == AssetType.EQUITY_MF and scrip_val:
                        name_lower = scrip_val.lower()
                        if any(kw in name_lower for kw in _DEBT_MF_KEYWORDS):
                            asset_type = AssetType.DEBT_MF

                    cg = CapitalGain(
                        gain_type=GainType(gain_dict.get("gain_type", "STCG")),
                        asset_type=asset_type,
                        sale_value=float(gain_dict.get("sell_value", 0)),
                        cost_of_acquisition=float(gain_dict.get("buy_value", 0)),
                        gain_amount=gain_val,
                        isin=isin_val or None,
                        scrip_name=scrip_val or None,
                        acquisition_date=acquisition_date,
                    )
                    capital_gains.append(cg)
                except Exception as e:
                    errors.append(f"CapitalGain construction error: {e}")

        # Warn when F&O or speculation income is present — those are business income
        # (not CG) and require ITR-3; they are NOT included in this computation.
        fno_field = doc.get("fields", {}).get("fno_total")
        if fno_field and fno_field.get("value"):
            try:
                fno_amt = float(fno_field["value"])
                if fno_amt != 0:
                    errors.append(
                        f"WARNING: F&O income of ₹{fno_amt:,.0f} detected in "
                        f"{doc.get('doc_type', 'document')}. F&O income is treated as "
                        "business income and requires ITR-3. It is NOT included in this "
                        "computation — please consult a CA."
                    )
            except (TypeError, ValueError):
                pass

        spec_field = doc.get("fields", {}).get("speculation_total")
        if spec_field and spec_field.get("value"):
            try:
                spec_amt = float(spec_field["value"])
                if spec_amt != 0:
                    errors.append(
                        f"WARNING: Intraday/speculation income of ₹{spec_amt:,.0f} detected. "
                        "This is taxable as business income under Schedule BP and is NOT "
                        "included in the capital gains computation."
                    )
            except (TypeError, ValueError):
                pass

        # Warn if any debt MF trades were reclassified — helps the user understand
        # why their tax may be higher than expected (slab rate vs 12.5%).
        debt_mf_gain = sum(
            g.gain_amount for g in capital_gains
            if g.asset_type.value == "debt_mf"
        )
        if debt_mf_gain > 0:
            errors.append(
                f"INFO: {debt_mf_gain:,.0f} in debt MF gains classified as slab-rate income "
                f"(Finance Act 2023, Section 50AA). These will be added to your taxable income "
                f"at your income slab rate, not at the equity MF rate of 12.5%."
            )

    # ---- Other income -------------------------------------------------------
    other_income = float(gap_fill.get("other_income") or 0)
    house_property_income = float(gap_fill.get("house_property_income") or 0)

    # ---- Advance tax / TDS --------------------------------------------------
    advance_tax = float(gap_fill.get("advance_tax_paid") or 0)
    tds_total   = float(gap_fill.get("tds_total") or 0)
    tcs_total   = float(gap_fill.get("tcs_total") or 0)

    # ---- Assemble ExtractedTaxData ------------------------------------------
    try:
        extracted = ExtractedTaxData(
            salary_income=salary_income,
            capital_gains=capital_gains,
            other_income=other_income,
            house_property_income=house_property_income,
            deductions=deductions,
            advance_tax_paid=advance_tax,
            tds_total=tds_total,
            tcs_total=tcs_total,
        )
    except Exception as e:
        errors.append(f"ExtractedTaxData construction error: {e}")
        extracted = ExtractedTaxData()

    return {
        "extracted_data": extracted.model_dump(),
        "current_act": "compute_tax",
        "errors": errors,
    }
