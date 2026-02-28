from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SaleItem:
    sell_price: float
    fee_percent: float


@dataclass(slots=True)
class DealEconomicInput:
    buy_price: float
    funding_source: str
    deal_type: str
    investor_id: str | None = None
    capital_balance: float = 0.0
    cash_low_threshold: float = 0.0
    rate_base: float = 0.0
    rate_low_cash: float = 0.0
    investor_profit_rate: float = 0.0
    bargain_bonus_enabled: bool = False
    bargain_amount: float = 0.0
    bargain_bonus_rate: float = 0.0
    bargain_bonus_cap_share_of_profit: float = 0.0
