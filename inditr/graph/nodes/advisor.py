"""
Act 5 — Tax Advisor node.
Targeted at young adults (22-35) optimising their tax and investments.
- Conversational, friendly, zero-jargon where possible
- Proactive money-saving tips computed by the engine — not guessed
- What-if scenario runner: "what if I max my 80C?" → engine answers
- Regime switch break-even analysis
- LTCG annual harvesting, ELSS vs PPF, NPS dual-benefit, health insurance framing
- Routes to human_final_review when user is ready to proceed
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from inditr.models.state import TaxFilingState
from inditr.models.tax_data import GainType, AssetType

# ──────────────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────────────

_MAX_80C = 150_000
_MAX_80CCD_1B = 50_000
_MAX_80D_SELF = 25_000
_LTCG_EXEMPTION = 125_000
_MAX_54EC = 5_000_000      # ₹50L Section 54EC bond investment cap per FY
_EPF_TAXABLE_THRESHOLD = 250_000  # Own EPF contribution above ₹2.5L/yr has taxable interest

_READY_TO_FILE_RE = re.compile(
    r"\b(proceed|ready\s+to\s+file|file\s+now|looks?\s+good|confirm|go\s+ahead|submit|yes,?\s+file|done|let'?s\s+file)\b",
    re.IGNORECASE,
)

_WHATIF_RE = re.compile(
    r"\b(what\s+if|if\s+I|suppose\s+I|hypothetically|scenario|simulate|try\s+with|what\s+would\s+happen"
    r"|if\s+i\s+(invest|put|contribute|pay|buy|take|start)|max\s+(out|the)|let'?s\s+say|assume\s+i)\b",
    re.IGNORECASE,
)


def _fmt(amount: float) -> str:
    """Format Indian rupee amount with commas."""
    return f"₹{amount:,.0f}"


# ──────────────────────────────────────────────────────────────────────────────
# Context builder for the system prompt
# ──────────────────────────────────────────────────────────────────────────────

def _build_computation_context(state: TaxFilingState) -> str:
    computation_raw = state.get("computation")
    if not computation_raw:
        return "No tax computation available yet."

    try:
        from inditr.models.computation import TaxComputation
        c = TaxComputation(**computation_raw)
        old = c.old_regime
        new = c.new_regime
        rec = c.recommended_regime
        savings = c.savings_from_recommendation

        profile_raw = state.get("filer_profile", {}) or {}
        extracted_raw = state.get("extracted_data", {}) or {}
        salary_raw = extracted_raw.get("salary_income") or {}
        gross = salary_raw.get("gross_salary", 0)
        deductions_raw = extracted_raw.get("deductions") or {}
        c80 = deductions_raw.get("sec_80c", 0) or 0
        c80d = deductions_raw.get("sec_80d", 0) or 0
        c80ccd = deductions_raw.get("sec_80ccd_1b", 0) or 0
        c80tta = deductions_raw.get("sec_80tta", 0) or 0
        hp_loss = extracted_raw.get("house_property_income", 0) or 0
        other = extracted_raw.get("other_income", 0) or 0

        lines = [
            f"FILER: {profile_raw.get('name', 'User')}, DOB {profile_raw.get('date_of_birth', 'unknown')}",
            f"GROSS SALARY: {_fmt(gross)}",
            f"OTHER INCOME: {_fmt(other)} | HOUSE PROPERTY: {_fmt(hp_loss)}",
            f"CURRENT DEDUCTIONS: 80C={_fmt(c80)}, 80D={_fmt(c80d)}, 80CCD(1B)={_fmt(c80ccd)}, 80TTA={_fmt(c80tta)}",
            f"UNUSED 80C ROOM: {_fmt(max(0, _MAX_80C - c80))} | UNUSED 80CCD(1B) ROOM: {_fmt(max(0, _MAX_80CCD_1B - c80ccd))}",
            "",
            f"OLD REGIME  → Taxable: {_fmt(old.taxable_income)} | Tax: {_fmt(old.total_tax_liability)} | Net: {_fmt(old.net_payable_refundable)}",
            f"NEW REGIME  → Taxable: {_fmt(new.taxable_income)} | Tax: {_fmt(new.total_tax_liability)} | Net: {_fmt(new.net_payable_refundable)}",
            "",
            f"RECOMMENDATION: {rec.upper()} REGIME saves {_fmt(savings)} — {c.recommendation_reason}",
        ]
        return "\n".join(lines)
    except Exception as e:
        return f"(Error: {e})"


# ──────────────────────────────────────────────────────────────────────────────
# System prompt — young adult focused
# ──────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = """\
You are IndITR Advisor — a sharp, friendly Indian tax & investment advisor for AY 2026-27.
Your users are young working adults (22-35) who want to pay less tax AND build wealth smartly.
Talk like a knowledgeable friend, not a government booklet. Be direct, actionable, relatable.
All tax numbers come from the engine — never make up figures; explain the engine's results.

━━━ THIS FILER'S NUMBERS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{computation_context}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AY 2026-27 RULES (know these cold)
───────────────────────────────────
NEW REGIME (default, no deductions except std):
  Slabs: 0-4L=0% | 4-8L=5% | 8-12L=10% | 12-16L=15% | 16-20L=20% | 20-24L=25% | >24L=30%
  Std deduction ₹75K. 87A rebate: zero tax if income ≤ ₹12L (max rebate ₹60K).
  Marginal relief near ₹12L threshold. No 80C/80D/HRA available.

OLD REGIME (worthwhile only if deductions are substantial):
  Slabs: 0-2.5L=0% | 2.5-5L=5% | 5-10L=20% | >10L=30%
  Std deduction ₹50K. 87A rebate if income ≤ ₹5L (max ₹12.5K).
  Deductions: 80C max ₹1.5L | 80CCD(1B) extra ₹50K NPS | 80D max ₹25K (self/family)
  80TTA ₹10K (savings a/c interest) | HRA exemption | home loan interest Section 24b (max ₹2L)

CAPITAL GAINS — AY 2026-27:
  Equity/MF held < 1 yr (STCG 111A): 20% flat — 87A rebate DOES NOT apply
  Equity/MF held ≥ 1 yr (LTCG 112A): 12.5% on gains ABOVE ₹1.25L — 87A rebate DOES NOT apply
  ₹1.25L LTCG exemption resets every financial year — harvest it annually!
  Property acquired after Jul 23, 2024: 12.5% (no indexation)
  Property acquired before Jul 23, 2024: lower of (12.5%) vs (20% + indexation) — engine picks best
    CII for FY 2025-26 = 376 (CBDT notified July 1, 2025). FY 2024-25 = 363.
    Indexed cost = original cost × 376 ÷ CII of purchase year. Give users this number on request.
  Debt MF bought after Apr 1, 2023: always taxed at slab rate regardless of how long you hold
  Share buyback (Budget 2026): taxed as CG now, not dividend
  SGB (Sovereign Gold Bond): redemption after 8 years = COMPLETELY TAX-FREE (even from LTCG). Before 8 yr = 20% LTCG.

CAPITAL GAINS REINVESTMENT EXEMPTIONS (applies in both regimes — HUGE savings for property sellers):
  Section 54: Sold residential house? Buy/construct another house in India within 2 yrs (buy) or 3 yrs (construct).
    Full LTCG exempt if full sale consideration reinvested. Deposit unused proceeds in CGAS before filing.
  Section 54EC: Sold any property? Invest up to ₹50L in NHAI/REC bonds within 6 months.
    5-yr lock-in. Interest ~5.25% taxable but CG tax fully saved. Run what-if to show savings.
  Section 54F: Sold non-residential asset (gold, unlisted equity, commercial property)?
    Invest full net sale consideration in ONE residential house for full LTCG exemption (proportional if partial).
    Condition: must not own more than 1 house on date of sale.
  PROACTIVE TIP: if user has property LTCG, ALWAYS surface these options even if they didn't ask.

SURCHARGE: 50L-1Cr=10% | 1-2Cr=15% | 2-5Cr=25% | >5Cr=25% (new) / 37% (old)
  STCG 111A and LTCG 112A: surcharge capped at 15%
Cess: 4% on tax+surcharge always.

ADVANCE TAX (very important for CG earners / salaried with side income):
  If total tax after TDS > ₹10,000, you must pay advance tax during the year.
  Missed advance tax → Section 234B interest: 1%/month from Apr 1 of assessment year till filing.
  Missed instalments → Section 234C: 1%/month for 3 months per missed instalment.
  CG realised after Sep 15: 234C interest is waived if full tax paid by Mar 31. Pay immediately after CG event.
  If user has a refund: they've likely overpaid — no interest issue; just file early for faster refund.

INVESTMENT PRODUCTS TO KNOW (for young adults):
  ELSS (Equity Linked Savings Scheme): counts for 80C, 3-yr lock-in (shortest among 80C options),
    equity returns (historically 12-15% CAGR) — best 80C choice for wealth building for young investors.
    SIP of ₹12,500/month = ₹1.5L/year = full 80C. Tax on exit: LTCG 12.5% above ₹1.25L.
  PPF: counts for 80C, 15-yr lock-in, ~7.1% interest, EEE tax status (fully tax-free).
    Good for risk-averse or for guaranteed returns portion.
  NPS Tier-1: 80CCD(1B) gives ₹50K EXTRA deduction over 80C limit. At 30% slab = ₹15K savings.
    Locked till 60. At retirement: 60% lump sum tax-free, 40% annuity (taxable).
    Good for retirement corpus alongside ELSS.
  SGB (Sovereign Gold Bond): better than physical gold — 2.5% annual interest (taxable) + CG exempt at 8-yr maturity
    IF you subscribed at original issue. Budget 2026 (effective AY 2027-28): SGBs bought on secondary market
    no longer get 8-yr exemption. For FY 2025-26 redemptions, all 8-yr holders still qualify.
    For gold investors: always prefer SGB over physical gold/gold ETF, but buy at original issue price for tax benefit.
  VPF (Voluntary PF): same as EPF, EEE tax status, but caution — if OWN contribution > ₹2.5L/year,
    interest on excess is TAXABLE. For most salaried, 12% of basic = well under ₹2.5L.
  Term Insurance: not a tax investment but 80C-eligible for premium. Critical to buy young (cheap).
  Health Insurance: 80D deduction ₹25K self/family. Buy young = low premium + deduction.
    Parents' health insurance: additional ₹25K (₹50K if senior) deduction under 80D.

VDA / CRYPTO (Section 115BBH) — WARN PROACTIVELY IF USER MENTIONS CRYPTO:
  ALL crypto/VDA gains: 30% flat + 4% cess = 31.2% effective. No LTCG/STCG distinction. No holding period benefit.
  No deduction except cost of acquisition. Losses in one coin CANNOT offset gains in another. ZERO carry forward.
  TDS 1% (Section 194S) by Indian exchanges — check Form 26AS for credit.
  Foreign exchanges: no TDS deducted; must pay full tax via advance tax. Also declare in Schedule FA.
  Must file ITR-2 for VDA income — ITR-1 not allowed.
  Strategy: tax-loss harvesting is useless for VDA (no set-off). Better to hold rather than churn.

OTHER IMPORTANT DEDUCTIONS (old regime only):
  80E (education loan interest): ZERO cap. All interest deductible for 8 years from year repayment starts.
    Students with study loans: this is often the most overlooked deduction. Don't miss it.
  80G (donations): PM CARES/CMRF = 100% deductible. Other approved NGOs = 50%, subject to 10% GTI cap.
    Only if you have receipts and the org's 80G registration number.
  Section 89(1) (salary arrears): If you received salary arrears for earlier years in this FY,
    you can claim relief under Section 89(1) to avoid extra tax from lump-sum receipt. File Form 10E on
    IT portal BEFORE filing ITR. Many employees miss this and overpay.

NEXT FINANCIAL YEAR PLANNING:
  After filing, tell the user: "For FY 2026-27, inform your employer which regime you want for TDS —
  do this in April. If you don't declare, employer defaults to new regime."
  Form 12BB must be submitted to employer at year start to claim HRA/home loan/80C/LIC for TDS under old regime.

WHAT-IF SCENARIOS — if user asks hypothetical questions, emit:
  WHATIF_SCENARIO: {{"key_delta": value}}
  Supported deltas: sec_80c_delta, sec_80d_delta, sec_80ccd_1b_delta, sec_80tta_delta,
    gross_salary_delta, other_income_delta, advance_tax_delta, home_loan_interest_delta,
    hra_exemption_delta, sec_80e_delta, sec_80g_delta,
    sec_54_exemption_delta, sec_54ec_exemption_delta, sec_54f_exemption_delta
  Examples:
    "what if I max 80C" → {{"sec_80c_delta": <headroom>}}
    "what if I buy health insurance for 25K" → {{"sec_80d_delta": 25000}}
    "what if I invest 50L in 54EC bonds" → {{"sec_54ec_exemption_delta": 5000000}}
    "what if I claim education loan interest of 80K" → {{"sec_80e_delta": 80000}}
    "what if I max everything" → all deltas combined in one JSON

BEHAVIOUR
─────────
- Lead with the number (savings/cost), then explain why.
- Use simple analogies. E.g. "ELSS is basically a tax-saving mutual fund with the shortest lock-in".
- Always show the actual ₹ saving from any action, using engine numbers.
- Compare both regimes when giving investment advice (deductions only matter in old regime).
- For young adults on new regime: explain the trade-off clearly — "yes 80C saves tax under old regime,
  but you'd need to invest enough to overcome the regime difference".
- Break-even framing: "you need ₹X in deductions for old regime to beat new regime for you."
- For property sellers: ALWAYS proactively mention Sec 54/54EC/54F — the tax saving can be massive.
- For education loan holders: ALWAYS ask about 80E — zero cap, often forgotten.
- For those with salary arrears: mention Section 89(1) and Form 10E BEFORE filing.
- If user asks about SIPs, MFs, or investments beyond tax: give brief, grounded advice anchored
  to their tax situation, then say "but for detailed investment planning, consider a SEBI-RIA."
- If they ask about illegal schemes, aggressive avoidance, or fake HRA: refuse clearly, explain risks.
- If they want to proceed/file: say READY_TO_FILE
- End every substantive tax advice with a brief reminder to verify before filing.
"""


# ──────────────────────────────────────────────────────────────────────────────
# What-if scenario runner
# ──────────────────────────────────────────────────────────────────────────────

def _run_whatif(state: TaxFilingState, scenario: dict[str, Any]) -> str:
    from inditr.engine.regime import compare_regimes
    from inditr.models.tax_data import ExtractedTaxData
    from inditr.models.profile import FilerProfile
    from inditr.models.computation import TaxComputation

    extracted_raw = state.get("extracted_data") or {}
    profile_raw = state.get("filer_profile") or {}
    computation_raw = state.get("computation") or {}

    if not extracted_raw or not profile_raw or not computation_raw:
        return "Cannot run scenario — tax data not yet computed."

    try:
        base = TaxComputation(**computation_raw)
        profile = FilerProfile(**profile_raw)
        mod = copy.deepcopy(extracted_raw)

        # Salary
        if "gross_salary_delta" in scenario:
            sal = mod.get("salary_income") or {}
            sal["gross_salary"] = (sal.get("gross_salary") or 0) + scenario["gross_salary_delta"]
            mod["salary_income"] = sal

        # Deductions
        ded = mod.get("deductions") or {}
        for field, key in [
            ("sec_80c",             "sec_80c_delta"),
            ("sec_80d",             "sec_80d_delta"),
            ("sec_80ccd_1b",        "sec_80ccd_1b_delta"),
            ("sec_80tta",           "sec_80tta_delta"),
            ("home_loan_interest",  "home_loan_interest_delta"),
            ("hra_exemption",       "hra_exemption_delta"),
            ("sec_80e",             "sec_80e_delta"),
            ("sec_80g",             "sec_80g_delta"),
            ("sec_54_exemption",    "sec_54_exemption_delta"),
            ("sec_54ec_exemption",  "sec_54ec_exemption_delta"),
            ("sec_54f_exemption",   "sec_54f_exemption_delta"),
        ]:
            if key in scenario:
                ded[field] = (ded.get(field) or 0) + scenario[key]
        mod["deductions"] = ded

        if "other_income_delta" in scenario:
            mod["other_income"] = (mod.get("other_income") or 0) + scenario["other_income_delta"]
        if "advance_tax_delta" in scenario:
            mod["advance_tax_paid"] = (mod.get("advance_tax_paid") or 0) + scenario["advance_tax_delta"]

        result = compare_regimes(ExtractedTaxData(**mod), profile)

        base_rec = base.recommended_regime
        base_tax = (base.old_regime if base_rec == "old" else base.new_regime).total_tax_liability

        new_rec = result.recommended_regime
        new_tax = (result.old_regime if new_rec == "old" else result.new_regime).total_tax_liability
        saving = base_tax - new_tax

        lines = [
            "WHAT-IF RESULT:",
            f"  Old Regime: taxable {_fmt(result.old_regime.taxable_income)} → tax {_fmt(result.old_regime.total_tax_liability)}",
            f"  New Regime: taxable {_fmt(result.new_regime.taxable_income)} → tax {_fmt(result.new_regime.total_tax_liability)}",
            f"  Best option: {new_rec.upper()} REGIME",
            "",
            (f"  Saves {_fmt(saving)} vs current plan." if saving > 0
             else f"  Costs {_fmt(-saving)} MORE than current plan." if saving < 0
             else "  No change in total tax."),
        ]
        return "\n".join(lines)

    except Exception as e:
        return f"Scenario error: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Proactive suggestions — young-adult focused, all numbers from engine
# ──────────────────────────────────────────────────────────────────────────────

def _generate_suggestions(state: TaxFilingState) -> list[str]:
    suggestions: list[str] = []

    computation_raw = state.get("computation") or {}
    extracted_raw = state.get("extracted_data") or {}
    if not computation_raw or not extracted_raw:
        return suggestions

    try:
        from inditr.models.computation import TaxComputation
        from inditr.models.tax_data import ExtractedTaxData, Deductions
        from inditr.models.profile import FilerProfile
        from inditr.engine.regime import compare_regimes

        c = TaxComputation(**computation_raw)
        profile_raw = state.get("filer_profile") or {}
        profile = FilerProfile(**profile_raw)
        extracted = ExtractedTaxData(**extracted_raw)

        ded = extracted.deductions or Deductions()
        sal = extracted.salary_income
        old = c.old_regime
        new = c.new_regime
        rec = c.recommended_regime
        rec_tax_obj = new if rec == "new" else old

        gross = sal.gross_salary if sal else 0
        c80   = ded.sec_80c or 0
        c80d  = ded.sec_80d or 0
        c80ccd = ded.sec_80ccd_1b or 0
        c80tta = ded.sec_80tta or 0

        # ── Tip 1: Regime break-even — show exactly what investment makes old regime worth it ──
        if rec == "new" and c.savings_from_recommendation > 0:
            # Simulate maxing all deductions; if old regime still worse, say so; else show crossover
            max_mod = copy.deepcopy(extracted_raw)
            max_ded = max_mod.get("deductions") or {}
            max_ded["sec_80c"] = _MAX_80C
            max_ded["sec_80ccd_1b"] = _MAX_80CCD_1B
            max_ded["sec_80d"] = _MAX_80D_SELF
            max_mod["deductions"] = max_ded
            try:
                max_result = compare_regimes(ExtractedTaxData(**max_mod), profile)
                max_saving_old = new.total_tax_liability - max_result.old_regime.total_tax_liability
                if max_saving_old > 0:
                    suggestions.append(
                        f"New regime is better for you right now by {_fmt(c.savings_from_recommendation)}. "
                        f"But if you max out 80C (₹1.5L) + NPS 80CCD(1B) (₹50K) + 80D (₹25K), "
                        f"old regime would save you {_fmt(max_saving_old)} more than new regime. "
                        f"Run 'what if I max everything' to see the exact numbers."
                    )
                else:
                    suggestions.append(
                        f"New regime saves you {_fmt(c.savings_from_recommendation)} even if you max every deduction. "
                        f"Stick with new regime — but still invest in ELSS/NPS for wealth building!"
                    )
            except Exception:
                pass

        elif rec == "old":
            suggestions.append(
                f"Old regime saves you {_fmt(c.savings_from_recommendation)} over new regime with your current deductions. "
                f"Make sure you have proofs ready for 80C/80D/HRA before filing."
            )

        # ── Tip 2: 80C headroom — ELSS-first framing for young adults ──
        if c80 < _MAX_80C:
            headroom = _MAX_80C - c80
            # Simulate maxing 80C
            sim = copy.deepcopy(extracted_raw)
            sim_d = sim.get("deductions") or {}
            sim_d["sec_80c"] = _MAX_80C
            sim["deductions"] = sim_d
            try:
                sim_result = compare_regimes(ExtractedTaxData(**sim), profile)
                saving = old.total_tax_liability - sim_result.old_regime.total_tax_liability
                if saving > 0:
                    sip_monthly = round(headroom / 12 / 500) * 500  # round to nearest 500
                    suggestions.append(
                        f"You have {_fmt(headroom)} unused 80C room. Filling it saves {_fmt(saving)} in old regime. "
                        f"Best option for your age: ELSS SIP of ~{_fmt(sip_monthly)}/month "
                        f"(3-yr lock-in, equity returns, same 80C benefit as PPF). "
                        f"PPF works if you want guaranteed returns — but lock-in is 15 years."
                    )
                else:
                    suggestions.append(
                        f"You have {_fmt(headroom)} unused 80C room — but maxing it won't change your tax "
                        f"(new regime is optimal for you). Still worth investing in ELSS for wealth building."
                    )
            except Exception:
                pass

        # ── Tip 3: NPS 80CCD(1B) — the ₹50K bonus deduction ──
        if c80ccd < _MAX_80CCD_1B:
            headroom_nps = _MAX_80CCD_1B - c80ccd
            sim = copy.deepcopy(extracted_raw)
            sim_d = sim.get("deductions") or {}
            sim_d["sec_80ccd_1b"] = _MAX_80CCD_1B
            sim["deductions"] = sim_d
            try:
                sim_result = compare_regimes(ExtractedTaxData(**sim), profile)
                saving = old.total_tax_liability - sim_result.old_regime.total_tax_liability
                if saving > 500:
                    suggestions.append(
                        f"NPS 80CCD(1B): invest {_fmt(headroom_nps)} in NPS Tier-1 for an EXTRA ₹50K "
                        f"deduction on top of 80C — saves {_fmt(saving)} in old regime. "
                        f"Locked till 60, but builds a solid retirement corpus. Great for early starters."
                    )
                else:
                    suggestions.append(
                        f"NPS 80CCD(1B) gives an extra ₹50K deduction beyond 80C in old regime. "
                        f"Even if tax saving is small now, starting NPS early is great for retirement compounding."
                    )
            except Exception:
                pass

        # ── Tip 4: Health insurance 80D — usually missing in young adults ──
        if c80d == 0:
            suggestions.append(
                f"No health insurance (80D) detected. Buying a family floater (₹5-10L cover) "
                f"costs ~₹8-15K/year and gives you a ₹25K 80D deduction in old regime. "
                f"Buy it young — premiums are cheapest now and only go up with age."
            )
        elif c80d < _MAX_80D_SELF:
            headroom_d = _MAX_80D_SELF - c80d
            suggestions.append(
                f"You can claim ₹{headroom_d:,.0f} more under 80D. "
                f"Parents' health insurance qualifies too — up to ₹25K extra (₹50K if they're senior citizens)."
            )

        # ── Tip 5: LTCG annual harvesting — simple, powerful ──
        cg_list = extracted.capital_gains or []
        _EQUITY_ASSET_TYPES = {AssetType.EQUITY, AssetType.EQUITY_MF}
        ltcg_112a = sum(
            g.gain_amount for g in cg_list
            if g.gain_type == GainType.LTCG
            and g.asset_type in _EQUITY_ASSET_TYPES
            and g.gain_amount > 0
        )
        if ltcg_112a < _LTCG_EXEMPTION:
            remaining = _LTCG_EXEMPTION - ltcg_112a
            suggestions.append(
                f"LTCG annual harvesting: you have {_fmt(remaining)} unused LTCG equity exemption this year. "
                f"You can book up to {_fmt(remaining)} in long-term equity/MF gains completely tax-free. "
                f"Sell and rebuy to reset your cost basis — use this every year to reduce future tax."
            )

        # ── Tip 6: Refund / payable ──
        net = rec_tax_obj.net_payable_refundable
        if net < -5_000:
            suggestions.append(
                f"You're owed a refund of {_fmt(-net)}! "
                f"File early (ITR portal opens April 1) and pre-validate your bank account on the portal "
                f"for faster credit — refunds typically land within 7-30 days when filed early."
            )
        elif net > 10_000:
            suggestions.append(
                f"You still have {_fmt(net)} payable. Pay it via 'Self Assessment Tax' on the IT portal "
                f"before filing to avoid interest under Sections 234B and 234C."
            )

        # ── Tip 7: HRA — if salaried and no HRA deduction claimed ──
        hra_claimed = ded.hra_exemption or 0
        if sal and sal.gross_salary and hra_claimed == 0:
            suggestions.append(
                "No HRA exemption detected. If you're paying rent, you can claim HRA exemption "
                "in the old regime — potentially the single biggest deduction available to salaried renters. "
                "Tell me your monthly rent and city to estimate your HRA savings."
            )

        # ── Tip 8: Section 54/54EC/54F — proactive for property sellers ──
        property_ltcg = sum(
            g.gain_amount for g in (extracted.capital_gains or [])
            if g.asset_type.value == "immovable_property" and g.gain_type.value == "LTCG" and g.gain_amount > 0
        )
        sec_54_already = (ded.sec_54_exemption or 0) + (ded.sec_54ec_exemption or 0) + (ded.sec_54f_exemption or 0)
        if property_ltcg > 0 and sec_54_already < property_ltcg:
            remaining_property_gain = property_ltcg - sec_54_already
            potential_tax_saving = int(remaining_property_gain * 0.125)  # 12.5% rate
            suggestions.append(
                f"You have property LTCG of {_fmt(property_ltcg)}. If not reinvested, the tax is "
                f"~{_fmt(potential_tax_saving)}. You may be able to ELIMINATE this tax:\n"
                f"  • **Section 54EC bonds** (NHAI/REC): invest up to ₹50L within 6 months → full CG exempt. "
                f"5-yr lock-in, ~5.25% interest. Say 'what if I invest 50L in 54EC bonds' to see exact savings.\n"
                f"  • **Section 54** (buying a new house): reinvest gains in residential property → full exemption.\n"
                f"  • **Section 54F** (sold non-residential asset): invest full sale consideration in a house → full exemption.\n"
                f"Act quickly — 54EC bonds must be bought within 6 months of the sale."
            )

        # ── Tip 9: Section 80E — education loan interest ──
        sec_80e_claimed = ded.sec_80e or 0
        if sec_80e_claimed == 0 and sal and sal.gross_salary:
            suggestions.append(
                "If you have an education loan (for yourself, spouse, children, or legal ward), "
                "you can claim the FULL interest paid as a deduction under Section 80E — no cap, old regime only. "
                "This is valid for up to 8 years from the year repayment started. Don't miss it if applicable."
            )

        # ── Tip 10: Advance tax warning if there's additional income or CG ──
        has_cg = bool(extracted.capital_gains)
        has_other = (extracted.other_income or 0) > 10_000
        if (has_cg or has_other) and net > 10_000:
            suggestions.append(
                f"You have ₹{net:,.0f} tax still payable. If this wasn't covered by advance tax payments "
                f"during FY 2025-26, you may owe interest under Section 234B (~1%/month from Apr 1). "
                f"Pay any remaining tax as Self-Assessment Tax on the IT portal (Challan 280, code 300) "
                f"BEFORE filing your return to stop interest from accumulating."
            )

        # ── Tip 11: Next FY regime declaration reminder ──
        suggestions.append(
            f"For FY 2026-27: tell your employer in April which tax regime you want for TDS. "
            f"If you don't declare, they'll default to the new regime. "
            f"If you plan old regime, submit Form 12BB with proof of investments (80C/80D/HRA/home loan)."
        )

    except Exception:
        pass

    return suggestions


# ──────────────────────────────────────────────────────────────────────────────
# Opening message builder
# ──────────────────────────────────────────────────────────────────────────────

def _build_opening_message(suggestions: list[str], state: TaxFilingState) -> str:
    """Build the first-entry advisor message with tips + invite for questions."""
    computation_raw = state.get("computation") or {}
    rec = "new"
    rec_tax = 0
    savings = 0
    try:
        from inditr.models.computation import TaxComputation
        c = TaxComputation(**computation_raw)
        rec = c.recommended_regime
        rec_tax = (c.new_regime if rec == "new" else c.old_regime).total_tax_liability
        savings = c.savings_from_recommendation
    except Exception:
        pass

    lines = [
        f"Your tax is computed. Best regime for you: **{rec.upper()}** → total tax {_fmt(rec_tax)} "
        f"(saves {_fmt(savings)} vs the other regime).",
        "",
        "Here's what I found that could save you more money:",
        "",
    ]
    lines += [f"**{i+1}.** {s}" for i, s in enumerate(suggestions)]
    lines += [
        "",
        "Ask me anything — 'how does ELSS work?', 'what if I invest ₹1L in NPS?', "
        "'should I switch to old regime?', 'explain my capital gains tax'. "
        "Or say **'ready to file'** when you're done.",
    ]
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Main node
# ──────────────────────────────────────────────────────────────────────────────

def tax_advisor(state: TaxFilingState) -> dict[str, Any]:
    """
    Conversational LLM node: young-adult-focused tax and investment advisor.
    Engine computes all numbers; LLM explains, advises, and routes conversation.
    """
    import litellm
    from inditr.graph.llm import MODEL

    messages = list(state.get("messages", []))
    errors = list(state.get("errors", []))
    advisor_suggestions = list(state.get("advisor_suggestions") or [])
    whatif_history = list(state.get("whatif_history") or [])

    # ── Generate proactive suggestions once ───────────────────────────────────
    if not advisor_suggestions:
        advisor_suggestions = _generate_suggestions(state)

    # ── Inject opening message on first advisor entry ─────────────────────────
    opening_injected = any(
        "Best regime for you" in m.get("content", "")
        for m in messages
    )
    if not opening_injected and advisor_suggestions:
        opening = _build_opening_message(advisor_suggestions, state)
        messages = messages + [{"role": "assistant", "content": opening}]

    # ── Detect what-if in last user message ───────────────────────────────────
    last_user = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"),
        None,
    )

    whatif_result_text = None
    if last_user and _WHATIF_RE.search(last_user):
        extractor_msgs = [
            {
                "role": "system",
                "content": (
                    "You are a JSON extractor for Indian tax what-if scenarios. "
                    "Given a hypothetical question, output ONLY a valid JSON object "
                    "using keys from: sec_80c_delta, sec_80d_delta, sec_80ccd_1b_delta, "
                    "sec_80tta_delta, gross_salary_delta, other_income_delta, "
                    "advance_tax_delta, home_loan_interest_delta, hra_exemption_delta. "
                    "Values are rupee amounts (positive = increase, negative = decrease). "
                    "If 'max' or 'full' is mentioned for a limit, use the full limit amount. "
                    "80C max = 150000, 80CCD(1B) max = 50000, 80D max = 25000. "
                    "Output ONLY the JSON object, no explanation."
                ),
            },
            {"role": "user", "content": last_user},
        ]
        try:
            ext_resp = litellm.completion(
                model=MODEL,
                messages=extractor_msgs,
                temperature=0.0,
                max_tokens=150,
            )
            ext_text = (ext_resp.choices[0].message.content or "").strip()
            json_match = re.search(r"\{[^{}]+\}", ext_text, re.DOTALL)
            if json_match:
                scenario = json.loads(json_match.group())
                if any(k.endswith("_delta") for k in scenario):
                    whatif_result_text = _run_whatif(state, scenario)
                    whatif_history = whatif_history + [{
                        "question": last_user,
                        "scenario": scenario,
                        "result": whatif_result_text,
                    }]
        except Exception as e:
            errors.append(f"What-if extraction error: {e}")

    # ── RAG: retrieve relevant rules for the user's question ─────────────────
    rag_block = ""
    if last_user:
        try:
            from inditr.rag.retriever import retrieve
            rag_ctx = retrieve(last_user, topk=4)
            if rag_ctx:
                rag_block = (
                    "\n\nRELEVANT TAX RULES RETRIEVED (authoritative; use verbatim figures):\n"
                    + rag_ctx
                )
        except Exception:
            pass

    # ── Build LLM conversation ─────────────────────────────────────────────────
    computation_context = _build_computation_context(state)
    system_content = _SYSTEM_PROMPT_TEMPLATE.format(
        computation_context=computation_context
    ) + rag_block

    llm_msgs: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
    llm_msgs.extend(messages)

    if whatif_result_text:
        llm_msgs.append({
            "role": "system",
            "content": (
                "The deterministic engine just ran this what-if scenario. "
                "Present these results to the user and explain what they mean:\n\n"
                + whatif_result_text
            ),
        })

    # ── LLM call ──────────────────────────────────────────────────────────────
    try:
        response = litellm.completion(
            model=MODEL,
            messages=llm_msgs,
            temperature=0.6,
            max_tokens=1024,
        )
        reply = response.choices[0].message.content or ""

        # Check for ready-to-file
        if "READY_TO_FILE" in reply or (last_user and _READY_TO_FILE_RE.search(last_user)):
            clean_reply = reply.replace("READY_TO_FILE", "").strip()
            if not clean_reply:
                clean_reply = (
                    "Let's go! Taking you to the final review. "
                    "Give everything one last look before you confirm."
                )
            new_messages = messages + [{"role": "assistant", "content": clean_reply}]
            return {
                "messages": new_messages,
                "advisor_suggestions": advisor_suggestions,
                "whatif_history": whatif_history,
                "current_act": "human_final_review",
                "errors": errors,
            }

        new_messages = messages + [{"role": "assistant", "content": reply}]
        return {
            "messages": new_messages,
            "advisor_suggestions": advisor_suggestions,
            "whatif_history": whatif_history,
            "current_act": "tax_advisor",
            "errors": errors,
        }

    except Exception as e:
        errors.append(f"LLM error in tax_advisor: {e}")
        fallback = (
            "Ran into a hiccup — but your tax numbers are ready above. "
            "Ask me anything or say 'ready to file' to proceed."
        )
        new_messages = messages + [{"role": "assistant", "content": fallback}]
        return {
            "messages": new_messages,
            "advisor_suggestions": advisor_suggestions,
            "whatif_history": whatif_history,
            "current_act": "tax_advisor",
            "errors": errors,
        }
