from __future__ import annotations


def bargain_bonus(
    profit: float,
    bargain_amount: float,
    enabled: bool,
    rate: float,
    cap_share_of_profit: float,
) -> float:
    if not enabled or profit <= 0 or bargain_amount <= 0:
        return 0.0
    return min(bargain_amount * rate, profit * cap_share_of_profit)
