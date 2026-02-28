from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from dotenv import load_dotenv

from bot.handlers.admin.handlers import registered_admin_handlers
from bot.handlers.finance.handlers import registered_finance_handlers
from bot.handlers.info.handlers import registered_info_handlers
from bot.handlers.tasks.handlers import registered_task_handlers
from bot.runtime.keyboards import main_menu
from bot.runtime.settings import load_settings


def _is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


def build_dispatcher(admin_ids: set[int]) -> Dispatcher:
    dp = Dispatcher()

    finance = set(registered_finance_handlers())
    tasks = set(registered_task_handlers())
    info = set(registered_info_handlers())
    admin = set(registered_admin_handlers())

    @dp.message(CommandStart())
    async def start(message: Message):
        user_id = message.from_user.id if message.from_user else 0
        is_admin = _is_admin(user_id, admin_ids)
        await message.answer(
            'Бот запущен ✅\nВыберите действие в меню.',
            reply_markup=main_menu(is_admin=is_admin),
        )

    @dp.message(Command('whoami'))
    async def whoami(message: Message):
        u = message.from_user
        if not u:
            await message.answer('Пользователь не определён.')
            return
        await message.answer(
            f'tg_id: {u.id}\nusername: @{u.username if u.username else "-"}\nfull_name: {u.full_name}'
        )

    @dp.message(F.text.in_(finance))
    async def finance_stub(message: Message):
        await message.answer('Финансовый модуль подключен. Этот сценарий будет делегирован в domain/flows.')

    @dp.message(F.text.in_(tasks))
    async def tasks_stub(message: Message):
        await message.answer('Модуль задач подключен. Этот сценарий будет делегирован в domain/task services.')

    @dp.message(F.text.in_(info))
    async def info_stub(message: Message):
        await message.answer('Инфо-модуль подключен.')

    @dp.message(F.text.in_(admin))
    async def admin_stub(message: Message):
        user_id = message.from_user.id if message.from_user else 0
        if not _is_admin(user_id, admin_ids):
            await message.answer('Доступ запрещён: только для администраторов.')
            return
        await message.answer('Админ-модуль подключен.')

    @dp.message()
    async def fallback(message: Message):
        await message.answer('Команда не распознана. Нажмите /start для меню.')

    return dp


async def run_bot() -> None:
    load_dotenv()
    settings = load_settings()
    bot = Bot(settings.bot_token)
    dp = build_dispatcher(settings.admin_ids)
    await dp.start_polling(bot)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_bot())
