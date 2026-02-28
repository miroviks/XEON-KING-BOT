from __future__ import annotations

from collections.abc import Iterable

from domain.models import SaleItem


def gross(items: Iterable[SaleItem]) -> float:
    return sum(item.sell_price for item in items)


def fee_total(items: Iterable[SaleItem]) -> float:
    return sum(item.sell_price * item.fee_percent / 100 for item in items)


def expenses_total(expenses: Iterable[float]) -> float:
    return sum(expenses)


def profit(gross_value: float, buy_price: float, expenses_value: float) -> float:
    return gross_value - buy_price - expenses_value


def net_in(gross_value: float, fee_total_value: float) -> float:
    return max(0.0, gross_value - fee_total_value)
