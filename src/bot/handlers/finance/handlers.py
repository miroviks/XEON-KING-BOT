from __future__ import annotations

FINANCE_COMMANDS = ["➕ Сделка", "➕ Расход", "📌 Статус сделки", "✅ Закрыть сделку", "💸 Выплаты", "📒 Долги", "💳 Счета"]


def registered_finance_handlers() -> list[str]:
    return FINANCE_COMMANDS
