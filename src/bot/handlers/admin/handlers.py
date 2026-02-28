from __future__ import annotations

ADMIN_COMMANDS = ["🛡 Админ", "➕ Добавить участника", "⭐ Сделать инвестором", "💰 Пополнить счет"]


def registered_admin_handlers() -> list[str]:
    return ADMIN_COMMANDS
