from __future__ import annotations


def refund_amount(input_refund: float | None, buy_price: float) -> float:
    return buy_price if input_refund is None else input_refund
