from __future__ import annotations


def cap_rate(capital_balance: float, cash_low_threshold: float, rate_base: float, rate_low_cash: float) -> float:
    return rate_low_cash if capital_balance < cash_low_threshold else rate_base


def cap_cut(profit: float, cap_rate_value: float) -> float:
    return max(0.0, profit * cap_rate_value)
