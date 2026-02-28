from __future__ import annotations

from domain.formulas.loan_rules import loan_total_to_repay


def loan_snapshot(principal: float, interest_percent: float, due_date: str) -> dict:
    return {
        "principal": principal,
        "interest_percent": interest_percent,
        "due_date": due_date,
        "total": loan_total_to_repay(principal, interest_percent),
    }
