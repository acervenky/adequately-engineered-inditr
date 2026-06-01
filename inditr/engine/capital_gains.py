"""
AY 2026-27 capital gains computation — pure Python, zero LLM.
Post-Budget 2024 rates. Finance Act 2023 (debt MF) and Budget 2024
(property indexation cutoff) rules incorporated.
"""
from __future__ import annotations
from datetime import date
from typing import Literal

from inditr.models.tax_data import CapitalGain, GainType, AssetType

# Cost Inflation Index — CBDT notification 1 Jul 2025 (FY 2025-26 / AY 2026-27)
_CII_FY2526 = 376

# LTCG exemption of ₹1,25,000 applies ONLY to equity and equity-MF (Section 112A)
_LTCG_112A_EXEMPTION = 125_000

# Post-Budget 2024 CG rates (unchanged in Budget 2026)
_STCG_111A_RATE = 0.20             # Section 111A — equity/equity-MF STCG
_LTCG_112A_RATE = 0.125            # Section 112A — equity/equity-MF LTCG
_LTCG_PROPERTY_RATE = 0.125        # Section 112 — property post-Jul-23-2024 (no indexation)
_LTCG_PROPERTY_INDEXED_RATE = 0.20 # Section 112 — property pre-Jul-23-2024 (with indexation)
_LTCG_OTHER_RATE = 0.125           # Other LTCG (pre-Apr-2023 debt MF at 24-month hold)

# Holding period thresholds (days)
_EQUITY_LTCG_DAYS = 365            # Listed equity / equity MF: 12 months
_DEBT_MF_LTCG_DAYS = 730          # Pre-Apr-2023 debt MF: 24 months (Finance Act 2023)
_PROPERTY_LTCG_DAYS = 730          # Immovable property: 24 months

_EQUITY_TYPES = {AssetType.EQUITY, AssetType.EQUITY_MF}


def classify_gain(
    buy_date: date | str,
    sell_date: date | str,
    asset_type: AssetType,
) -> Literal["STCG", "LTCG", "SLAB"]:
    """
    Classify a capital gain as STCG, LTCG, or SLAB.
    Returns "SLAB" for post-Apr-2023 debt MF (Finance Act 2023: no special rate,
    always taxed at slab rates regardless of holding period).
    """
    if isinstance(buy_date, str):
        buy_date = date.fromisoformat(buy_date)
    if isinstance(sell_date, str):
        sell_date = date.fromisoformat(sell_date)

    # Post-Apr-2023 debt MF: Finance Act 2023 removed LTCG status entirely.
    if asset_type == AssetType.DEBT_MF and buy_date >= date(2023, 4, 1):
        return "SLAB"

    # Share buyback: treated like equity for holding period purposes (FY 2026-27+).
    if asset_type == AssetType.BUYBACK:
        threshold = _EQUITY_LTCG_DAYS
    elif asset_type in _EQUITY_TYPES:
        threshold = _EQUITY_LTCG_DAYS
    elif asset_type == AssetType.IMMOVABLE_PROPERTY:
        threshold = _PROPERTY_LTCG_DAYS
    elif asset_type == AssetType.DEBT_MF:
        # Pre-Apr-2023 debt MF: 24 months for LTCG (corrected from 36 months)
        threshold = _DEBT_MF_LTCG_DAYS
    else:
        threshold = _EQUITY_LTCG_DAYS  # default: 12 months

    holding_days = (sell_date - buy_date).days
    return "LTCG" if holding_days >= threshold else "STCG"


def compute_stcg_111a_tax(stcg_equity_total: int) -> int:
    """STCG tax at 20% flat — Section 111A (listed equity / equity MF)."""
    return int(stcg_equity_total * _STCG_111A_RATE)


def compute_ltcg_112a_tax(ltcg_equity: int) -> int:
    """LTCG equity/equity-MF — Section 112A: 12.5% after ₹1,25,000 exemption."""
    taxable = max(0, ltcg_equity - _LTCG_112A_EXEMPTION)
    return int(taxable * _LTCG_112A_RATE)


def compute_ltcg_property_tax(
    ltcg_property_post_jul24: int,
    ltcg_property_pre_jul24_indexed: int = 0,
) -> int:
    """
    LTCG property tax — Section 112.
    - Post-Jul-23-2024: 12.5% without indexation (no choice).
    - Pre-Jul-23-2024 with indexed cost: aggregate_gains already chose the
      better option (20% indexed vs 12.5% unindexed) and passes the
      indexed gain here.
    Returns combined property LTCG tax.
    """
    tax_post = int(ltcg_property_post_jul24 * _LTCG_PROPERTY_RATE)
    tax_pre_indexed = int(ltcg_property_pre_jul24_indexed * _LTCG_PROPERTY_INDEXED_RATE)
    return tax_post + tax_pre_indexed


def compute_ltcg_other_tax(ltcg_other: int) -> int:
    """LTCG other (pre-Apr-2023 debt MF held 24+ months): 12.5% without indexation."""
    return int(ltcg_other * _LTCG_OTHER_RATE)


def _apply_setoffs(
    stcg_equity: float,
    stcg_other: float,
    ltcg_equity: float,
    ltcg_property: float,
    ltcg_other: float,
) -> tuple[float, float, float, float, float]:
    """
    Apply Section 74 set-off rules.
    1. Long-term losses set off only against long-term gains.
    2. Short-term losses set off against short-term gains first.
    3. Remaining short-term losses set off against long-term gains.
    4. Remaining long-term losses cannot offset short-term gains (carry forward).
    Returns (stcg_equity, stcg_other, ltcg_equity, ltcg_property, ltcg_other) after set-offs.
    """
    # --- Step 1: LTCL vs LTCG ---
    # Collect losses and offset against gains in order: property → other → equity
    ltcg_list = [ltcg_property, ltcg_other, ltcg_equity]
    for i in range(len(ltcg_list)):
        if ltcg_list[i] < 0:
            loss = -ltcg_list[i]
            ltcg_list[i] = 0.0
            for j in range(len(ltcg_list)):
                if j != i and ltcg_list[j] > 0:
                    offset = min(loss, ltcg_list[j])
                    ltcg_list[j] -= offset
                    loss -= offset
                    if loss <= 0:
                        break
            # Unabsorbed LTCL carried forward (not applicable to current year STCG)
    ltcg_property, ltcg_other, ltcg_equity = ltcg_list

    # --- Step 2: STCL vs STCG ---
    if stcg_equity < 0 and stcg_other > 0:
        offset = min(-stcg_equity, stcg_other)
        stcg_equity += offset
        stcg_other -= offset
    elif stcg_other < 0 and stcg_equity > 0:
        offset = min(-stcg_other, stcg_equity)
        stcg_other += offset
        stcg_equity -= offset

    # --- Step 3: Remaining STCL vs LTCG ---
    total_stcl = max(0.0, -stcg_equity) + max(0.0, -stcg_other)
    stcg_equity = max(0.0, stcg_equity)
    stcg_other = max(0.0, stcg_other)

    if total_stcl > 0:
        # Offset against LTCG property first, then other, then equity
        for i in range(len(ltcg_list)):
            if ltcg_list[i] > 0:
                offset = min(total_stcl, ltcg_list[i])
                ltcg_list[i] -= offset
                total_stcl -= offset
                if total_stcl <= 0:
                    break
        ltcg_property, ltcg_other, ltcg_equity = ltcg_list

    # Remaining LTCL cannot offset STCG — truncate to 0 (carry forward outside scope)
    ltcg_equity = max(0.0, ltcg_equity)
    ltcg_property = max(0.0, ltcg_property)
    ltcg_other = max(0.0, ltcg_other)

    return stcg_equity, stcg_other, ltcg_equity, ltcg_property, ltcg_other


def aggregate_gains(gains: list[CapitalGain]) -> dict:
    """
    Aggregate capital gains into tax buckets and apply Section 74 set-off rules.

    Returns dict with keys:
      stcg_equity_total    — equity/equity-MF STCG (Section 111A, 20%)
      stcg_other_total     — other-asset STCG (slab rate)
      ltcg_equity_total    — equity/equity-MF LTCG (Section 112A, 12.5% after ₹1.25L exempt)
      ltcg_property_total  — property LTCG post-Jul-23-2024 (Section 112, 12.5%)
      ltcg_property_indexed_total — property LTCG pre-Jul-23-2024 using indexed cost (20%)
      ltcg_other_total     — pre-Apr-2023 debt MF LTCG (12.5%)
      slab_cg_total        — post-Apr-2023 debt MF gains (slab rate, added to taxable income)
      stcg_111a_tax        — tax on equity STCG
      ltcg_112a_tax        — tax on equity LTCG
      ltcg_property_tax    — tax on property LTCG (both pre/post-Jul-2024)
      ltcg_other_tax       — tax on other LTCG
      # Legacy aliases for backward compatibility:
      stcg_equity_tax      — alias for stcg_111a_tax
      ltcg_tax             — total of all LTCG taxes
    """
    stcg_equity = 0.0
    stcg_other = 0.0
    ltcg_equity = 0.0
    ltcg_property = 0.0              # post-Jul-23-2024 property (unindexed)
    ltcg_property_pre_indexed = 0.0  # pre-Jul-23-2024 property gains computed on indexed cost
    ltcg_other = 0.0                 # pre-Apr-2023 debt MF held 24+ months
    slab_cg = 0.0                    # post-Apr-2023 debt MF (slab rate)

    for gain in gains:
        amt = gain.gain_amount

        # Post-Apr-2023 debt MF: always slab-taxed, no CG classification
        if gain.asset_type == AssetType.DEBT_MF and gain.is_post_apr2023_debt_mf:
            slab_cg += amt
            continue

        # Share buyback (FY 2026-27+): treated like equity for CG purposes
        if gain.asset_type == AssetType.BUYBACK:
            if gain.gain_type == GainType.STCG:
                stcg_equity += amt
            else:
                ltcg_equity += amt
            continue

        if gain.gain_type == GainType.STCG:
            if gain.asset_type in _EQUITY_TYPES:
                stcg_equity += amt
            else:
                stcg_other += amt
        else:  # LTCG
            if gain.asset_type in _EQUITY_TYPES:
                ltcg_equity += amt
            elif gain.asset_type == AssetType.IMMOVABLE_PROPERTY:
                if gain.can_use_indexation and gain.indexed_cost is not None:
                    # Pre-Jul-2024 property: choose lower of 12.5% (unindexed) vs 20% (indexed)
                    indexed_gain = gain.sale_value - gain.indexed_cost
                    unindexed_gain = amt
                    tax_indexed = max(0.0, indexed_gain) * _LTCG_PROPERTY_INDEXED_RATE
                    tax_unindexed = max(0.0, unindexed_gain) * _LTCG_PROPERTY_RATE
                    if tax_indexed <= tax_unindexed:
                        # Indexation is better (or equal)
                        ltcg_property_pre_indexed += max(0.0, indexed_gain)
                    else:
                        # Flat 12.5% is better
                        ltcg_property += max(0.0, unindexed_gain)
                else:
                    # Post-Jul-2024 or no indexed cost: 12.5% flat
                    ltcg_property += amt
            else:
                # Pre-Apr-2023 debt MF LTCG (24+ months)
                ltcg_other += amt

    # Apply Section 74 set-off rules
    stcg_equity, stcg_other, ltcg_equity, ltcg_property, ltcg_other = _apply_setoffs(
        stcg_equity, stcg_other, ltcg_equity, ltcg_property, ltcg_other
    )

    # Compute taxes
    stcg_111a_tax = compute_stcg_111a_tax(int(stcg_equity))
    ltcg_112a_tax = compute_ltcg_112a_tax(int(ltcg_equity))
    ltcg_property_tax = compute_ltcg_property_tax(int(ltcg_property), int(ltcg_property_pre_indexed))
    ltcg_other_tax = compute_ltcg_other_tax(int(ltcg_other))

    return {
        "stcg_equity_total": int(stcg_equity),
        "stcg_other_total": int(stcg_other),
        "ltcg_equity_total": int(ltcg_equity),
        "ltcg_property_total": int(ltcg_property),
        "ltcg_property_indexed_total": int(ltcg_property_pre_indexed),
        "ltcg_other_total": int(ltcg_other),
        "slab_cg_total": int(slab_cg),
        "stcg_111a_tax": stcg_111a_tax,
        "ltcg_112a_tax": ltcg_112a_tax,
        "ltcg_property_tax": ltcg_property_tax,
        "ltcg_other_tax": ltcg_other_tax,
        # Legacy aliases
        "stcg_equity_tax": stcg_111a_tax,
        "ltcg_tax": ltcg_112a_tax + ltcg_property_tax + ltcg_other_tax,
    }
