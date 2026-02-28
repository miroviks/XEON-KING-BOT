from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from bot.handlers.admin.handlers import registered_admin_handlers
from bot.handlers.finance.handlers import registered_finance_handlers
from bot.handlers.info.handlers import registered_info_handlers
from bot.handlers.tasks.handlers import registered_task_handlers


def main_menu(is_admin: bool) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []

    rows.append([KeyboardButton(text='➕ Сделка'), KeyboardButton(text='➕ Расход')])
    rows.append([KeyboardButton(text='📌 Статус сделки'), KeyboardButton(text='✅ Закрыть сделку')])
    rows.append([KeyboardButton(text='💸 Выплаты'), KeyboardButton(text='📒 Долги')])
    rows.append([KeyboardButton(text='📋 Мои задачи'), KeyboardButton(text='➕ Создать задачу')])
    rows.append([KeyboardButton(text='📄 Конфиг'), KeyboardButton(text='📤 Экспорт Excel')])

    if is_admin:
        rows.append([KeyboardButton(text='🛡 Админ')])

    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def all_known_commands() -> set[str]:
    values = set(registered_finance_handlers())
    values.update(registered_task_handlers())
    values.update(registered_info_handlers())
    values.update(registered_admin_handlers())
    values.add('/whoami')
    return values
