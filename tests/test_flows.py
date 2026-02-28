from domain.flows.deal_close_sold import close_sale
from domain.models import DealEconomicInput, SaleItem


def test_close_sale_zero_cuts_when_profit_non_positive():
    econ = DealEconomicInput(
        buy_price=60000,
        funding_source="capital",
        deal_type="resale",
        capital_balance=10000,
        cash_low_threshold=5000,
        rate_base=0.2,
        rate_low_cash=0.3,
        bargain_bonus_enabled=True,
        bargain_amount=5000,
        bargain_bonus_rate=0.2,
        bargain_bonus_cap_share_of_profit=0.1,
    )
    result = close_sale(econ, [SaleItem(10000, 10)], [1000])
    assert result.profit < 0
    assert result.cap_cut == 0
    assert result.inv_cut == 0
    assert result.bargain_bonus == 0
