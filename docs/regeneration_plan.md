# План миграции по шагам
1. Зафиксировать спецификации формул/флоу как источник истины.
2. Выделить формулы из монолита в `src/domain/formulas` без изменения выражений.
3. Перенести вычислительный блок закрытия сделки в `src/domain/flows/deal_close_sold.py`.
4. Вынести правила валидации в `src/domain/validation`.
5. Выделить DB-контракт в `src/infra/db/repository.py`.
6. Разнести обработчики команд по `src/bot/handlers/*`.
7. Добавить тесты на формулы, условия и алгоритм округления.
8. Подготовить карту трассировки `function -> formula -> table`.

# Целевая структура директорий
```text
src/
  bot/handlers/{finance,tasks,admin,info}/
  domain/
    formulas/
    flows/
    payouts/
    loans/
    validation/
  infra/db/
  parsers/
tests/
docs/
```

# Карта переносов функций
- `parse_money`, `parse_lines`, `parse_date` -> `src/parsers/input_parsers.py`
- `close_sale` core calc -> `src/domain/flows/deal_close_sold.py`
- `cap_rate_for_balance` -> `src/domain/formulas/capital_rules.py::cap_rate`
- `investor_rate`/investor cut logic -> `src/domain/formulas/investor_rules.py::inv_cut`
- Task weight math -> `src/domain/formulas/task_weights.py`
- Loan math -> `src/domain/formulas/loan_rules.py`
- Transaction/DB methods -> `src/infra/db/repository.py`

# Контрольные тест-кейсы
- `deal_profit`: gross, fee_total, profit, net_in
- `capital_rules`: cap_rate thresholds, cap_cut floor at zero
- `investor_rules`: exclusion for service deal types
- `bargain_bonus`: cap by share of profit
- `rounding`: cents floor + rest to largest with sum guarantee
- `loan_rules`: interest expense and total repay
- Guard: `profit <= 0` => zero cuts

# Риски и rollback-план
## Риски
- Поведенческие расхождения на edge-cases старого UI/FSM.
- Расхождение SQL-операций при неполной миграции DAO-методов.
- Неполный паритет по служебным командам бота.

## Rollback
1. Откат на предыдущий commit монолита.
2. Восстановление schema/config/runtime файлов из тега релиза.
3. Постепенный feature-flag rollout модульных flow поверх legacy.
