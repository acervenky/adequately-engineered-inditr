"""
TDS reconciliation — pure Python, zero LLM.
"""
from __future__ import annotations


def reconcile_tds(
    tds_sources: list[dict],
    total_tax_liability: int,
) -> dict:
    """
    Reconcile TDS/advance tax against total tax liability.

    tds_sources: list of dicts with keys:
        - source: str (e.g. "employer", "bank", "advance_tax")
        - amount: int

    Returns:
        {
            "total_tds": int,
            "total_tax_liability": int,
            "net_payable": int,   # positive = payable, negative = refund
            "refund": int,        # 0 if payable
            "shortfall": int,     # 0 if refund
        }
    """
    total_tds = sum(int(s.get("amount", 0)) for s in tds_sources)
    net = total_tax_liability - total_tds

    return {
        "total_tds": total_tds,
        "total_tax_liability": total_tax_liability,
        "net_payable": net,
        "refund": abs(net) if net < 0 else 0,
        "shortfall": net if net > 0 else 0,
    }
