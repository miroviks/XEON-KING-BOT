from __future__ import annotations


def loan_interest_expense(principal: float, interest_percent: float) -> float:
    return principal * interest_percent / 100


def loan_total_to_repay(principal: float, interest_percent: float) -> float:
    return principal + loan_interest_expense(principal, interest_percent)
