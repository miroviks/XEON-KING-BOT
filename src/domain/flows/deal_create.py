from __future__ import annotations


def bargain_amount(list_price: float, buy_price: float) -> float:
    return max(0.0, list_price - buy_price)
