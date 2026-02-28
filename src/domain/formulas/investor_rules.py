from __future__ import annotations


SERVICE_TYPES = {"service_build", "service_diagnostic"}


def inv_cut(profit: float, funding_source: str, deal_type: str, investor_profit_rate: float) -> float:
    if funding_source != "investor" or deal_type in SERVICE_TYPES:
        return 0.0
    return max(0.0, profit * investor_profit_rate)
