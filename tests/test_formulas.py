from domain.formulas.bargain_bonus import bargain_bonus
from domain.formulas.capital_rules import cap_cut, cap_rate
from domain.formulas.deal_profit import fee_total, gross, net_in, profit
from domain.formulas.investor_rules import inv_cut
from domain.formulas.loan_rules import loan_interest_expense, loan_total_to_repay
from domain.formulas.rounding import distribute_pool
from domain.models import SaleItem


def test_deal_profit_formula_block():
    items = [SaleItem(30000, 10), SaleItem(50000, 6)]
    gross_value = gross(items)
    fee_value = fee_total(items)
    profit_value = profit(gross_value, 60000, 8000)
    assert gross_value == 80000
    assert fee_value == 6000
    assert profit_value == 12000
    assert net_in(gross_value, fee_value) == 74000


def test_capital_rules_threshold():
    assert cap_rate(1000, 5000, 0.2, 0.35) == 0.35
    assert cap_rate(9000, 5000, 0.2, 0.35) == 0.2
    assert cap_cut(-1, 0.2) == 0


def test_investor_rules_with_exclusion():
    assert inv_cut(10000, "investor", "resale", 0.5) == 5000
    assert inv_cut(10000, "investor", "service_build", 0.5) == 0


def test_bargain_bonus_cap():
    assert bargain_bonus(10000, 8000, True, 0.2, 0.1) == 1000


def test_rounding_strategy_sum_guarantee():
    entries = [10.009, 10.009, 10.009]
    result = distribute_pool(entries, 30.03)
    assert sum(result) == 30.03


def test_loan_rules_formulas():
    assert loan_interest_expense(50000, 10) == 5000
    assert loan_total_to_repay(50000, 10) == 55000
