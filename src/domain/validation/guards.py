from __future__ import annotations


def validate_fee_percent(value: float) -> None:
    if value < 0:
        raise ValueError("fee_percent must be >= 0")


def zero_cuts_for_non_positive_profit(profit: float) -> bool:
    return profit <= 0
