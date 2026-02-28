from __future__ import annotations

INFO_COMMANDS = ["📄 Конфиг", "📤 Экспорт Excel", "/whoami"]


def registered_info_handlers() -> list[str]:
    return INFO_COMMANDS
