from __future__ import annotations

from dataclasses import dataclass

from domain.formulas.bargain_bonus import bargain_bonus
from domain.formulas.capital_rules import cap_cut, cap_rate
from domain.formulas.deal_profit import expenses_total, fee_total, gross, net_in, profit
from domain.formulas.investor_rules import inv_cut
from domain.models import DealEconomicInput, SaleItem


@dataclass(slots=True)
class DealCloseSoldResult:
    gross: float
    fee_total: float
    expenses_total: float
    profit: float
    net_in: float
    cap_rate: float
    cap_cut: float
    inv_cut: float
    bargain_bonus: float


def close_sale(economic_input: DealEconomicInput, sale_items: list[SaleItem], deal_expenses: list[float]) -> DealCloseSoldResult:
    gross_value = gross(sale_items)
    fee_total_value = fee_total(sale_items)
    expenses_value = expenses_total(deal_expenses)
    profit_value = profit(gross_value, economic_input.buy_price, expenses_value)
    cap_rate_value = cap_rate(
        economic_input.capital_balance,
        economic_input.cash_low_threshold,
        economic_input.rate_base,
        economic_input.rate_low_cash,
    )
    if profit_value <= 0:
        return DealCloseSoldResult(
            gross=gross_value,
            fee_total=fee_total_value,
            expenses_total=expenses_value,
            profit=profit_value,
            net_in=net_in(gross_value, fee_total_value),
            cap_rate=cap_rate_value,
            cap_cut=0.0,
            inv_cut=0.0,
            bargain_bonus=0.0,
        )

    return DealCloseSoldResult(
        gross=gross_value,
        fee_total=fee_total_value,
        expenses_total=expenses_value,
        profit=profit_value,
        net_in=net_in(gross_value, fee_total_value),
        cap_rate=cap_rate_value,
        cap_cut=cap_cut(profit_value, cap_rate_value),
        inv_cut=inv_cut(
            profit_value,
            economic_input.funding_source,
            economic_input.deal_type,
            economic_input.investor_profit_rate,
        ),
        bargain_bonus=bargain_bonus(
            profit=profit_value,
            bargain_amount=economic_input.bargain_amount,
            enabled=economic_input.bargain_bonus_enabled,
            rate=economic_input.bargain_bonus_rate,
            cap_share_of_profit=economic_input.bargain_bonus_cap_share_of_profit,
        ),
    )
