# Traceability: function -> formula -> table

| Function | Formula Spec | Affected Tables |
|---|---|---|
| `deal_profit.gross` | `formulas/deal_profit.yaml#gross` | `deal_items` |
| `deal_profit.fee_total` | `formulas/deal_profit.yaml#fee_total` | `deal_items` |
| `deal_profit.expenses_total` | `formulas/deal_profit.yaml#expenses_total` | `expenses` |
| `deal_profit.profit` | `formulas/deal_profit.yaml#profit` | `deals`, `deal_close_summary` |
| `deal_profit.net_in` | `formulas/deal_profit.yaml#net_in` | `transactions`, `accounts` |
| `capital_rules.cap_rate` | `formulas/capital_rules.yaml#cap_rate` | `accounts` |
| `capital_rules.cap_cut` | `formulas/capital_rules.yaml#cap_cut` | `payouts`, `deal_close_summary` |
| `investor_rules.inv_cut` | `formulas/investor_rules.yaml#inv_cut` | `payouts`, `transactions` |
| `bargain_bonus.bargain_bonus` | `formulas/bargain_bonus.yaml#bargain_bonus` | `payouts`, `deal_tasks` |
| `task_weights.apply_task_weight` | `formulas/task_weights.yaml` | `deal_tasks`, `deal_task_performers` |
| `rounding.distribute_pool` | `formulas/rounding.yaml` | `payouts` |
| `loan_rules.loan_interest_expense` | `formulas/loan_rules.yaml#loan_interest_expense` | `expenses`, `loans` |
| `loan_rules.loan_total_to_repay` | `formulas/loan_rules.yaml#loan_total_to_repay` | `loans`, `transactions` |
| `deal_close_sold.close_sale` | `flows/deal_close_sold.yaml` | `deal_items`, `expenses`, `transactions`, `payouts`, `deal_close_summary` |
