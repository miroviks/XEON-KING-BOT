import os
import re
import asyncio
import zipfile
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Iterable

import aiosqlite
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile
)

from apscheduler.schedulers.asyncio import AsyncIOScheduler
import openpyxl

try:
    import tomllib  # py3.11+
except Exception:
    import tomli as tomllib  # type: ignore


# ============================
# Globals / runtime singletons
# ============================
dp = Dispatcher()
BOT: Optional[Bot] = None
CFG: Dict[str, Any] = {}
DBH: "DB"  # type: ignore


# ============================
# Settings / config
# ============================
@dataclass
class Settings:
    bot_token: str
    db_path: str
    config_path: str
    data_dir: str


def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is empty. Put token into .env")
    return Settings(
        bot_token=token,
        db_path=os.getenv("DB_PATH", "./data/bot.sqlite3"),
        config_path=os.getenv("CONFIG_PATH", "./config.txt"),
        data_dir=os.getenv("DATA_DIR", "./data"),
    )


def load_config(path: str) -> Dict[str, Any]:
    raw = Path(path).read_bytes()
    return tomllib.loads(raw.decode("utf-8"))


# ============================
# Text / labels
# ============================
DEAL_TYPE_LABEL = {
    "resale": "Перепродажа",
    "repair": "Под ремонт",
    "pc_build_project": "Сборка ПК (проект)",
    "service_build": "Услуга: сборка",
    "service_diagnostic": "Услуга: диагностика",
}

STATUS_ICON = {"open": "🟢", "sold": "🔴", "return": "🟡"}

DELIVERY_LABEL = {
    "avito": "Авито-доставка",
    "other_service": "Другой сервис",
    "own": "Своя доставка",
    "in_person": "Лично",
}

PRIORITY_ICON = {"low": "🟢", "mid": "🟠", "high": "🔴"}

TASK_LABEL = {
    "found": "🔎 Нашёл",
    "estimate": "📊 Оценка",
    "acquire": "🛒 Приобрёл",
    "test": "🧪 Тест/Обслуживание",
    "repair": "🛠️ Ремонт",
    "list": "📸 Выставил",
    "communicate": "💬 Общение",
    "sell": "📦 Продал",
    # services:
    "parts_prep": "📦 Подготовка",
    "deliver": "🚚 Доставка",
    "execute": "🛠️ Выполнение",
    "handoff": "🤝 Передача",
}


# ============================
# Helpers
# ============================
def parse_money(s: str) -> float:
    s = s.replace(" ", "").replace(",", ".").strip()
    return float(s)


def parse_lines(text: str) -> List[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def parse_date(s: str) -> str:
    s = s.strip()
    if s in ("1", "1.") or s.lower() in ("сегодня", "today"):
        return date.today().isoformat()
    if s in ("2", "2.") or s.lower() in ("вчера", "yesterday"):
        return (date.today() - timedelta(days=1)).isoformat()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m:
        return s
    m = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})$", s)
    if m:
        dd, mm, yy = m.groups()
        return f"{yy}-{mm}-{dd}"
    raise ValueError("bad date format")


def choice_list(title: str, options: List[str]) -> str:
    lines = [title]
    for i, opt in enumerate(options, start=1):
        lines.append(f"{i}. {opt}")
    return "\n".join(lines)


async def send_message_safe(tg_id: int, text: str, reply_markup=None):
    if BOT is None:
        return
    try:
        await BOT.send_message(tg_id, text, reply_markup=reply_markup)
    except Exception:
        pass


# ============================
# DB
# ============================
class DB:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def connect(self):
        return aiosqlite.connect(self.db_path)

    async def init(self, schema_path: str):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as con:
            sql = Path(schema_path).read_text("utf-8")
            await con.executescript(sql)
            await con.commit()
        await self.migrate()

    async def migrate(self):
        """Best-effort migrations for older DBs."""
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row

            async def ensure_col(table: str, col: str, coldef: str):
                cur = await con.execute(f"PRAGMA table_info({table})")
                cols = [r["name"] for r in await cur.fetchall()]
                if col not in cols:
                    await con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coldef}")

            # users
            await ensure_col("users", "display_name", "TEXT")

            # deals
            await ensure_col("deals", "location_holder", "TEXT")
            await ensure_col("deals", "last_listing_update", "TEXT")

            # deal_items
            await ensure_col("deal_items", "forecast_after", "REAL")
            await ensure_col("deal_items", "sell_price", "REAL")
            await ensure_col("deal_items", "sell_date", "TEXT")
            await ensure_col("deal_items", "delivery_type", "TEXT")
            await ensure_col("deal_items", "fee_percent", "REAL")

            # payouts & summaries
            # if tables don't exist, schema.sql creates them; but guard anyway
            await con.commit()

    async def ensure_base_accounts(self, cfg: Dict[str, Any]):
        async with self.connect() as con:
            await con.execute("INSERT OR IGNORE INTO accounts(account_id, title, balance) VALUES('capital','Капитал',0)")
            for inv in cfg.get("investors", {}).get("list", []):
                acc_id = f"investor:{inv['id']}"
                await con.execute("INSERT OR IGNORE INTO accounts(account_id, title, balance) VALUES(?,?,0)", (acc_id, f"Инвестор {inv['name']}"))
            await con.commit()

    async def upsert_user(self, tg_id: int, username: Optional[str], full_name: str):
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT display_name FROM users WHERE tg_id=?", (tg_id,))
            row = await cur.fetchone()
            existing_display = row["display_name"] if row else None
            await con.execute(
                """
                INSERT INTO users(tg_id, username, full_name, display_name)
                VALUES(?,?,?,?)
                ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name
                """,
                (tg_id, username, full_name, existing_display),
            )
            await con.commit()

    async def set_display_name(self, tg_id: int, display_name: str):
        async with self.connect() as con:
            await con.execute("UPDATE users SET display_name=? WHERE tg_id=?", (display_name, tg_id))
            await con.commit()

    async def get_user(self, tg_id: int):
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT * FROM users WHERE tg_id=?", (tg_id,))
            return await cur.fetchone()

    async def set_user_flags(self, tg_id: int, **kwargs):
        fields, vals = [], []
        for k, v in kwargs.items():
            if k in ("is_admin", "is_member", "is_investor", "is_active"):
                fields.append(f"{k}=?")
                vals.append(1 if v else 0)
        if not fields:
            return
        vals.append(tg_id)
        async with self.connect() as con:
            await con.execute(f"UPDATE users SET {', '.join(fields)} WHERE tg_id=?", vals)
            await con.commit()

    async def list_active_members(self):
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute(
                "SELECT * FROM users WHERE is_active=1 AND is_member=1 ORDER BY COALESCE(display_name, full_name, username)"
            )
            return await cur.fetchall()

    async def list_admins_and_members(self):
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT * FROM users WHERE is_active=1 AND (is_admin=1 OR is_member=1)")
            return await cur.fetchall()

    async def toggle_mute_regular(self, tg_id: int) -> int:
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT mute_regular FROM users WHERE tg_id=?", (tg_id,))
            row = await cur.fetchone()
            new_val = 0 if (row and row["mute_regular"] == 1) else 1
            await con.execute("UPDATE users SET mute_regular=? WHERE tg_id=?", (new_val, tg_id))
            await con.commit()
            return new_val

    async def create_transaction(self, date_str: str, account_from: Optional[str], account_to: Optional[str],
                                 amount: float, reason: str, deal_id: Optional[int], created_by: int):
        async with self.connect() as con:
            await con.execute(
                "INSERT INTO transactions(date, account_from, account_to, amount, reason, deal_id, created_by) VALUES(?,?,?,?,?,?,?)",
                (date_str, account_from, account_to, amount, reason, deal_id, created_by),
            )
            if account_from:
                await con.execute("UPDATE accounts SET balance=balance-? WHERE account_id=?", (amount, account_from))
            if account_to:
                await con.execute("UPDATE accounts SET balance=balance+? WHERE account_id=?", (amount, account_to))
            await con.commit()

    async def get_account_balance(self, account_id: str) -> float:
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT balance FROM accounts WHERE account_id=?", (account_id,))
            row = await cur.fetchone()
            return float(row["balance"]) if row else 0.0

    async def create_loan(self, investor_id: str, principal: float, interest_percent: float, due_date: str) -> int:
        async with self.connect() as con:
            cur = await con.execute(
                "INSERT INTO loans(investor_id, principal, interest_percent, due_date, status) VALUES(?,?,?,?, 'open')",
                (investor_id, principal, interest_percent, due_date),
            )
            await con.commit()
            return int(cur.lastrowid)

    async def get_loan(self, loan_id: int):
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT * FROM loans WHERE loan_id=?", (loan_id,))
            return await cur.fetchone()

    async def list_open_loans(self):
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT * FROM loans WHERE status='open' ORDER BY due_date")
            return await cur.fetchall()

    async def close_loan_paid(self, loan_id: int):
        async with self.connect() as con:
            await con.execute("UPDATE loans SET status='paid' WHERE loan_id=?", (loan_id,))
            await con.commit()

    async def create_deal(self, payload: Dict[str, Any]) -> int:
        async with self.connect() as con:
            cur = await con.execute(
                """
                INSERT INTO deals(created_at, status, deal_type, funding_source, investor_id, loan_id,
                                  list_price, buy_price, bargain_amount, notes, location_holder, last_listing_update)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    payload["created_at"],
                    payload["status"],
                    payload["deal_type"],
                    payload["funding_source"],
                    payload.get("investor_id"),
                    payload.get("loan_id"),
                    payload["list_price"],
                    payload["buy_price"],
                    payload["bargain_amount"],
                    payload.get("notes"),
                    payload.get("location_holder"),
                    payload.get("last_listing_update"),
                ),
            )
            await con.commit()
            return int(cur.lastrowid)

    async def get_deal(self, deal_id: int):
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT * FROM deals WHERE deal_id=?", (deal_id,))
            return await cur.fetchone()

    async def list_recent_open_deals(self, limit: int = 15):
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT * FROM deals WHERE closed_at IS NULL ORDER BY deal_id DESC LIMIT ?", (limit,))
            return await cur.fetchall()

    async def list_recent_deals(self, limit: int = 15):
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT * FROM deals ORDER BY deal_id DESC LIMIT ?", (limit,))
            return await cur.fetchall()

    async def list_closed_deals(self, limit: int = 30):
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT * FROM deals WHERE closed_at IS NOT NULL ORDER BY deal_id DESC LIMIT ?", (limit,))
            return await cur.fetchall()

    async def close_deal(self, deal_id: int, status: str, closed_at: str):
        async with self.connect() as con:
            await con.execute("UPDATE deals SET status=?, closed_at=? WHERE deal_id=?", (status, closed_at, deal_id))
            await con.commit()

    async def reopen_deal(self, deal_id: int):
        async with self.connect() as con:
            await con.execute("UPDATE deals SET closed_at=NULL, status='bought' WHERE deal_id=?", (deal_id,))
            await con.commit()

    async def touch_listing_update(self, deal_id: int, ts: str):
        async with self.connect() as con:
            await con.execute("UPDATE deals SET last_listing_update=? WHERE deal_id=?", (ts, deal_id))
            await con.commit()

    async def add_deal_item(self, deal_id: int, item: Dict[str, Any]) -> int:
        async with self.connect() as con:
            cur = await con.execute(
                "INSERT INTO deal_items(deal_id, category, subcategory, title, estimate_before, forecast_after) VALUES(?,?,?,?,?,?)",
                (deal_id, item.get("category", "Электроника"), item["subcategory"], item["title"], item.get("estimate_before"), item.get("forecast_after")),
            )
            await con.commit()
            return int(cur.lastrowid)

    async def list_deal_items(self, deal_id: int):
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT * FROM deal_items WHERE deal_id=? ORDER BY item_id", (deal_id,))
            return await cur.fetchall()

    async def update_item_sale(self, item_id: int, sell_price: float, sell_date: str, delivery_type: str, fee_percent: float):
        async with self.connect() as con:
            await con.execute(
                "UPDATE deal_items SET sell_price=?, sell_date=?, delivery_type=?, fee_percent=? WHERE item_id=?",
                (sell_price, sell_date, delivery_type, fee_percent, item_id),
            )
            await con.commit()

    async def add_expense(self, exp: Dict[str, Any]) -> int:
        async with self.connect() as con:
            cur = await con.execute(
                "INSERT INTO expenses(date, amount, exp_type, description, deal_id, created_by) VALUES(?,?,?,?,?,?)",
                (exp["date"], exp["amount"], exp["exp_type"], exp.get("description"), exp.get("deal_id"), exp.get("created_by")),
            )
            await con.commit()
            return int(cur.lastrowid)

    async def sum_expenses_for_deal(self, deal_id: int) -> float:
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT COALESCE(SUM(amount),0) AS s FROM expenses WHERE deal_id=?", (deal_id,))
            row = await cur.fetchone()
            return float(row["s"] or 0.0)

    async def done_task_types(self, deal_id: int) -> List[str]:
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT DISTINCT task_type FROM deal_tasks WHERE deal_id=?", (deal_id,))
            rows = await cur.fetchall()
            return [r["task_type"] for r in rows]

    async def create_deal_task(self, task: Dict[str, Any], performer_ids: List[int]) -> int:
        async with self.connect() as con:
            cur = await con.execute(
                "INSERT INTO deal_tasks(deal_id, task_type, complexity, ai_mult, comment, done_date, created_by) VALUES(?,?,?,?,?,?,?)",
                (task["deal_id"], task["task_type"], task.get("complexity"), task.get("ai_mult", 1.0), task.get("comment"), task["done_date"], task.get("created_by")),
            )
            task_id = int(cur.lastrowid)
            for pid in performer_ids:
                await con.execute("INSERT INTO deal_task_performers(task_id, performer_id) VALUES(?,?)", (task_id, pid))
            await con.commit()
            return task_id

    async def list_deal_tasks(self, deal_id: int):
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT * FROM deal_tasks WHERE deal_id=? ORDER BY task_id", (deal_id,))
            return await cur.fetchall()

    async def list_task_performers(self, task_id: int) -> List[int]:
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT performer_id FROM deal_task_performers WHERE task_id=?", (task_id,))
            rows = await cur.fetchall()
            return [int(r["performer_id"]) for r in rows]

    async def create_payout(self, deal_id: int, amount: float, kind: str, *, user_id: Optional[int] = None, investor_id: Optional[str] = None):
        async with self.connect() as con:
            await con.execute(
                "INSERT INTO payouts(deal_id, user_id, investor_id, amount, kind, is_paid) VALUES(?,?,?,?,?,0)",
                (deal_id, user_id, investor_id, amount, kind),
            )
            await con.commit()

    async def list_payouts(self, deal_id: int):
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT * FROM payouts WHERE deal_id=? ORDER BY payout_id", (deal_id,))
            return await cur.fetchall()

    async def mark_payouts_paid(self, deal_id: int):
        async with self.connect() as con:
            await con.execute("UPDATE payouts SET is_paid=1, paid_at=datetime('now') WHERE deal_id=?", (deal_id,))
            await con.commit()

    async def has_paid_payouts(self, deal_id: int) -> bool:
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute("SELECT COUNT(1) AS c FROM payouts WHERE deal_id=? AND is_paid=1", (deal_id,))
            row = await cur.fetchone()
            return (row["c"] or 0) > 0

    async def rollback_close_side_effects(self, deal_id: int):
        """Rollback close transactions/auto-expenses/sale fields/payouts/summary."""
        async with self.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute(
                """SELECT * FROM transactions
                   WHERE deal_id=? AND reason IN (
                       'Выручка (нетто после комиссий)',
                       'Возврат закупки инвестору (тело)',
                       'Возврат покупки (деньги вернули)'
                   )""",
                (deal_id,),
            )
            txs = await cur.fetchall()
            for t in txs:
                amt = float(t["amount"])
                frm = t["account_from"]
                to = t["account_to"]
                if frm:
                    await con.execute("UPDATE accounts SET balance=balance+? WHERE account_id=?", (amt, frm))
                if to:
                    await con.execute("UPDATE accounts SET balance=balance-? WHERE account_id=?", (amt, to))
                await con.execute("DELETE FROM transactions WHERE id=?", (t["id"],))

            await con.execute(
                """DELETE FROM expenses
                   WHERE deal_id=? AND exp_type IN ('Комиссия доставки','Проценты по долгу')
                     AND (description LIKE 'Автоматически%' OR description IS NULL)""",
                (deal_id,),
            )

            await con.execute(
                """UPDATE deal_items
                   SET sell_price=NULL, sell_date=NULL, delivery_type=NULL, fee_percent=NULL
                   WHERE deal_id=?""",
                (deal_id,),
            )

            await con.execute("DELETE FROM payouts WHERE deal_id=?", (deal_id,))
            await con.execute("DELETE FROM deal_close_summary WHERE deal_id=?", (deal_id,))
            await con.commit()

    
async def upsert_close_summary(self, deal_id: int, payload: Dict[str, float]):
    """Upsert summary for deal_close_summary."""
    async with self.connect() as con:
        await con.execute(
            """
            INSERT INTO deal_close_summary(
                deal_id, profit, cap_rate, cap_cut, inv_cut, performer_pool, bargain_bonus, payouts_total
            )
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(deal_id) DO UPDATE SET
                profit=excluded.profit,
                cap_rate=excluded.cap_rate,
                cap_cut=excluded.cap_cut,
                inv_cut=excluded.inv_cut,
                performer_pool=excluded.performer_pool,
                bargain_bonus=excluded.bargain_bonus,
                payouts_total=excluded.payouts_total
            """,
            (
                deal_id,
                float(payload.get("profit", 0.0)),
                float(payload.get("cap_rate", 0.0)),
                float(payload.get("cap_cut", 0.0)),
                float(payload.get("inv_cut", 0.0)),
                float(payload.get("performer_pool", 0.0)),
                float(payload.get("bargain_bonus", 0.0)),
                float(payload.get("payouts_total", 0.0)),
            ),
        )
        await con.commit()
async def sum_expected_sales(self, deal_id: int) -> float:
        items = await self.list_deal_items(deal_id)
        total = 0.0
        for it in items:
            if it["forecast_after"] is not None:
                total += float(it["forecast_after"])
            elif it["estimate_before"] is not None:
                total += float(it["estimate_before"])
        return total

# --- Совместимость: в некоторых версиях методы DB могли быть определены как функции верхнего уровня.
# Привязываем их к классу DB, чтобы не падало AttributeError.
try:
    if not hasattr(DB, "upsert_close_summary") and "upsert_close_summary" in globals():
        DB.upsert_close_summary = upsert_close_summary  # type: ignore
    if not hasattr(DB, "sum_expected_sales") and "sum_expected_sales" in globals():
        DB.sum_expected_sales = sum_expected_sales  # type: ignore
    if not hasattr(DB, "sum_expected_sales_fallback") and "sum_expected_sales" in globals():
        DB.sum_expected_sales_fallback = sum_expected_sales  # type: ignore
except Exception:
    pass

async def sum_expected_sales_fallback(self, deal_id: int) -> float:
    # Fallback: sum forecast_after or estimate_before
    items = await self.list_deal_items(deal_id)
    total = 0.0
    for it in items:
        if it["forecast_after"] is not None:
            total += float(it["forecast_after"])
        elif it["estimate_before"] is not None:
            total += float(it["estimate_before"])
    return total


# ============================
# Business rules / calculations
# ============================
def cap_rate_for_balance(cfg: Dict[str, Any], capital_cash: float) -> float:
    threshold = float(cfg["capital"]["cash_low_threshold"])
    return float(cfg["capital"]["rate_low_cash"] if capital_cash < threshold else cfg["capital"]["rate_base"])


def investor_rate(cfg: Dict[str, Any], investor_id: str) -> float:
    for inv in cfg.get("investors", {}).get("list", []):
        if inv["id"] == investor_id:
            return float(inv["profit_rate"])
    return 0.0


def complexity_mult(cfg: Dict[str, Any], level: Optional[str]) -> float:
    """Множитель сложности/типа работы.
    Фиксированные коэффициенты:
      - detail=1.0, project=1.2 (Выставил)
      - pvz=1.0, own_delivery=1.2 (Продал)
      - repair_low=0.8, repair_mid=1.0, repair_high=1.2 (Ремонт)
      - usual=1.0, long=1.2 (Обслуживание)
      - test_only=1.0, service_test=1.35 (Тест/Обслуживание)
    Остальные (low/mid/high): из cfg["complexity"].
    """
    if not level:
        return float(cfg["complexity"]["mult_mid"])
    level = str(level).lower()

    fixed = {
        "detail": 1.0,
        "project": 1.2,
        "pvz": 1.0,
        "own_delivery": 1.2,
        "usual": 1.0,
        "long": 1.2,
        "repair_low": 0.8,
        "repair_mid": 1.0,
        "repair_high": 1.2,
        "test_only": 1.0,
        "service_test": 1.35,
    }
    if level in fixed:
        return float(fixed[level])

    if level == "low":
        return float(cfg["complexity"]["mult_low"])
    if level == "high":
        return float(cfg["complexity"]["mult_high"])
    return float(cfg["complexity"]["mult_mid"])





def item_from_line(line: str, allowed_subcats: List[str]) -> Dict[str, Any]:
    parts = [p.strip() for p in line.split(":")]
    if len(parts) < 3:
        raise ValueError("Формат: GPU:Название:Оценка")
    sub = parts[0].upper()
    if sub not in allowed_subcats:
        raise ValueError(f"Неизвестная подкатегория: {sub}")
    est = parse_money(parts[-1])
    title = ":".join(parts[1:-1]).strip()
    if not title:
        raise ValueError("Пустое название")
    return {"subcategory": sub, "title": title, "estimate_before": est, "category": "Электроника"}


def parse_sale_line(s: str) -> Tuple[float, str, str, float]:
    parts = [p.strip() for p in s.split(";") if p.strip()]
    if len(parts) != 4:
        raise ValueError("Формат: цена;дата;доставка;комиссия% (пример: 25000;сегодня;avito;5)")
    price = parse_money(parts[0])
    sdate = parse_date(parts[1])
    delivery = parts[2].lower()
    if delivery not in DELIVERY_LABEL:
        raise ValueError("Доставка: avito / other_service / own / in_person")
    fee = parse_money(parts[3])
    if fee < 0:
        raise ValueError("Комиссия% не может быть отрицательной")
    return price, sdate, delivery, fee


async def ensure_user(*args) -> aiosqlite.Row:
    """Backward-compatible:
    - ensure_user(user)
    - ensure_user(db, cfg, user)
    """
    if len(args) == 1:
        db = DBH
        cfg = CFG
        u = args[0]
    elif len(args) == 3:
        db, cfg, u = args
    else:
        raise TypeError("ensure_user expects (user) or (db, cfg, user)")

    await db.upsert_user(u.id, u.username, (u.full_name or "").strip())
    row = await db.get_user(u.id)
    if not row:
        raise RuntimeError("user upsert failed")

    admins = [x.lower().lstrip("@") for x in cfg.get("roles", {}).get("admin_usernames", [])]
    if u.username and u.username.lower().lstrip("@") in admins and row["is_admin"] == 0:
        await db.set_user_flags(u.id, is_admin=True, is_member=True, is_active=True)
        row = await db.get_user(u.id)

    if row["is_admin"] == 1 and row["is_member"] == 0:
        await db.set_user_flags(u.id, is_member=True)
        row = await db.get_user(u.id)

    return row


async def members_numbered(*args) -> Tuple[str, Dict[str, int]]:
    """Backward-compatible:
    - members_numbered()
    - members_numbered(db)
    """
    if len(args) == 0:
        db = DBH
    elif len(args) == 1:
        db = args[0]
    else:
        raise TypeError("members_numbered expects () or (db,)")

    members = await db.list_active_members()
    mapping: Dict[str, int] = {}
    lines = ["Выберите исполнителя (цифра или несколько через запятую):"]
    for i, m in enumerate(members, start=1):
        name = m["display_name"] or m["full_name"] or (("@"+m["username"]) if m["username"] else str(m["tg_id"]))
        mapping[str(i)] = int(m["tg_id"])
        lines.append(f"{i}. {name}")
    return "\n".join(lines), mapping


def parse_choice_ids(text: str, mapping: Dict[str, int]) -> List[int]:
    raw = text.replace(" ", "")
    parts = [p for p in raw.split(",") if p]
    out: List[int] = []
    for p in parts:
        if p not in mapping:
            raise ValueError(f"Неизвестный номер: {p}")
        out.append(mapping[p])
    if not out:
        raise ValueError("Пустой выбор")
    return out


# ============================
# Keyboards
# ============================
def main_menu_kb(is_admin: bool) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="📋 Задачи"), KeyboardButton(text="💰 Финансы")],
        [KeyboardButton(text="ℹ️ Информация"), KeyboardButton(text="⚙️ Настройки")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="🛡 Админ")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def finance_menu_kb() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="➕ Сделка"), KeyboardButton(text="➕ Расход")],
        [KeyboardButton(text="📌 Статус сделки"), KeyboardButton(text="✅ Закрыть сделку")],
        [KeyboardButton(text="💸 Выплаты"), KeyboardButton(text="📒 Долги")],
        [KeyboardButton(text="✏️ Редактировать закрытую")],
        [KeyboardButton(text="💳 Счета")],
        [KeyboardButton(text="⬅️ Назад")],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def tasks_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои задачи"), KeyboardButton(text="➕ Создать задачу")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True
    )


def info_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📤 Экспорт Excel")],
            [KeyboardButton(text="📄 Конфиг")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True
    )


def settings_kb(muted: bool) -> ReplyKeyboardMarkup:
    label = "🔔 Включить обычные уведомления" if muted else "🔕 Отключить обычные уведомления"
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=label)], [KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True)


def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить участника"), KeyboardButton(text="⭐ Сделать инвестором")],
            [KeyboardButton(text="💰 Пополнить счет")],
            [KeyboardButton(text="⬅️ Назад")],
        ],
        resize_keyboard=True
    )


async def deal_line(d: aiosqlite.Row) -> str:
    deal_id = int(d["deal_id"])
    closed = d["closed_at"] is not None
    icon = STATUS_ICON["open"]
    if closed:
        icon = STATUS_ICON["return"] if d["status"] == "return" else STATUS_ICON["sold"]

    exp_sales = await DBH.sum_expected_sales(deal_id)
    exp_sales_str = f"{int(exp_sales)}р" if exp_sales > 0 else "—"

    buy = float(d["buy_price"] or 0.0)
    exp = await DBH.sum_expenses_for_deal(deal_id)
    profit_pct = "—"
    if buy > 0 and exp_sales > 0:
        pct = round(((exp_sales - buy - exp) / buy) * 100)
        profit_pct = f"{pct}%"

    done_types = set(await DBH.done_task_types(deal_id))
    dt = d["deal_type"]
    if dt == "service_build":
        required = set(CFG["tasks"]["service_build"].keys())
    elif dt == "service_diagnostic":
        required = set(CFG["tasks"]["service_diagnostic"].keys())
    elif dt == "repair":
        required = set(CFG["tasks"]["repair"].keys())
    else:
        required = set(CFG["tasks"]["resale"].keys())
    done = len(done_types.intersection(required))
    total = len(required)
    progress = "✅" if (total > 0 and done >= total) else f"{done}/{total}"

    return f"#{deal_id} {icon} {DEAL_TYPE_LABEL.get(dt, dt)} · {exp_sales_str} · {profit_pct} 📍 {progress}"


async def inline_deals(deals: List[aiosqlite.Row], prefix: str) -> InlineKeyboardMarkup:
    rows = []
    for d in deals:
        rows.append([InlineKeyboardButton(text=await deal_line(d), callback_data=f"{prefix}:{d['deal_id']}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{prefix}:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inline_tasks(deal_id: int, task_keys: List[str]) -> InlineKeyboardMarkup:
    rows = []
    for k in task_keys:
        rows.append([InlineKeyboardButton(text=TASK_LABEL.get(k, k), callback_data=f"taskpick:{deal_id}:{k}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"taskpick:{deal_id}:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def inline_back(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{prefix}:back")]])


# ============================
# FSM states
# ============================
class DealCreate(StatesGroup):
    date = State()
    funding = State()
    investor_pick = State()
    loan_interest = State()
    loan_due = State()
    list_price = State()
    buy_price = State()
    deal_type = State()
    notes = State()
    location = State()
    location_text = State()
    items = State()


class ExpenseCreate(StatesGroup):
    amount = State()
    date = State()
    exp_type = State()
    description = State()
    relate = State()
    pick_deal = State()


class DealTaskAdd(StatesGroup):
    pick_performers = State()
    complexity = State()
    ai_mult = State()
    comment = State()
    done_date = State()


class CloseDeal(StatesGroup):
    pick_deal = State()
    outcome = State()
    sale_input = State()
    return_refund = State()


class PayoutsFlow(StatesGroup):
    pick_deal = State()


class GenTaskCreate(StatesGroup):
    assignee = State()
    priority = State()
    title = State()
    description = State()
    due = State()


class LoansFlow(StatesGroup):
    pick_loan = State()


class AdminAddUser(StatesGroup):
    user_id = State()
    display_name = State()


class AdminMakeInvestor(StatesGroup):
    user_id = State()


class AdminTopUpAccount(StatesGroup):
    account = State()
    amount = State()
    reason = State()


# ============================
# Handlers - main navigation
# ============================
@dp.message(CommandStart())
async def on_start(message: Message, state: FSMContext):
    u = await ensure_user(message.from_user)
    await state.clear()
    await message.answer("✅ Готово. /whoami покажет ваш tg_user_id.", reply_markup=main_menu_kb(bool(u["is_admin"])))


@dp.message(Command("whoami"))
async def whoami(message: Message):
    await ensure_user(message.from_user)
    u = message.from_user
    await message.answer(f"Ваш tg_user_id: {u.id}\nusername: @{u.username or '—'}")


@dp.message(F.text == "⬅️ Назад")
async def back_to_main(message: Message, state: FSMContext):
    u = await ensure_user(message.from_user)
    await state.clear()
    await message.answer("🏠", reply_markup=main_menu_kb(bool(u["is_admin"])))


@dp.message(F.text == "💰 Финансы")
async def finance_menu(message: Message):
    await ensure_user(message.from_user)
    await message.answer("💰", reply_markup=finance_menu_kb())


@dp.message(F.text == "📋 Задачи")
async def tasks_menu(message: Message):
    await ensure_user(message.from_user)
    await message.answer("📋", reply_markup=tasks_menu_kb())


@dp.message(F.text == "ℹ️ Информация")
async def info_menu(message: Message):
    await ensure_user(message.from_user)
    await message.answer("ℹ️", reply_markup=info_menu_kb())


@dp.message(F.text == "⚙️ Настройки")
async def settings_menu(message: Message):
    u = await ensure_user(message.from_user)
    await message.answer("⚙️", reply_markup=settings_kb(bool(u["mute_regular"])))


@dp.message(F.text.in_(["🔕 Отключить обычные уведомления", "🔔 Включить обычные уведомления"]))
async def toggle_notifications(message: Message):
    await ensure_user(message.from_user)
    new_val = await DBH.toggle_mute_regular(message.from_user.id)
    await message.answer("✅ Готово.", reply_markup=settings_kb(bool(new_val)))


# ============================
# Admin
# ============================
@dp.message(F.text == "🛡 Админ")
async def admin_menu(message: Message):
    u = await ensure_user(message.from_user)
    if u["is_admin"] != 1:
        return await message.answer("⛔ Недостаточно прав.")
    await message.answer("🛡", reply_markup=admin_menu_kb())


@dp.message(F.text == "➕ Добавить участника")
async def admin_add_member(message: Message, state: FSMContext):
    u = await ensure_user(message.from_user)
    if u["is_admin"] != 1:
        return await message.answer("⛔ Недостаточно прав.")
    await state.clear()
    await state.set_state(AdminAddUser.user_id)
    await message.answer("Введите tg_user_id участника (он получает его через /whoami).")


@dp.message(AdminAddUser.user_id)
async def admin_add_member_id(message: Message, state: FSMContext):
    u = await ensure_user(message.from_user)
    if u["is_admin"] != 1:
        return await state.clear()
    try:
        uid = int(message.text.strip())
    except Exception:
        return await message.answer("Введите число.")
    await DBH.set_user_flags(uid, is_member=True, is_active=True)
    await state.update_data(user_id=uid)
    await state.set_state(AdminAddUser.display_name)
    await message.answer("Введите отображаемое имя (например: Стас).")


@dp.message(AdminAddUser.display_name)
async def admin_add_member_name(message: Message, state: FSMContext):
    u = await ensure_user(message.from_user)
    if u["is_admin"] != 1:
        return await state.clear()
    uid = int((await state.get_data())["user_id"])
    name = message.text.strip()
    await DBH.set_display_name(uid, name)
    await state.clear()
    await message.answer(f"✅ Участник добавлен: {name} ({uid}).")


@dp.message(F.text == "⭐ Сделать инвестором")
async def admin_make_investor(message: Message, state: FSMContext):
    u = await ensure_user(message.from_user)
    if u["is_admin"] != 1:
        return await message.answer("⛔ Недостаточно прав.")
    await state.clear()
    await state.set_state(AdminMakeInvestor.user_id)
    await message.answer("Введите tg_user_id инвестора.")


@dp.message(AdminMakeInvestor.user_id)
async def admin_make_investor_id(message: Message, state: FSMContext):
    u = await ensure_user(message.from_user)
    if u["is_admin"] != 1:
        return await state.clear()
    try:
        uid = int(message.text.strip())
    except Exception:
        return await message.answer("Введите число.")
    await DBH.set_user_flags(uid, is_investor=True, is_active=True)
    await state.clear()
    await message.answer("✅ Готово.")


@dp.message(F.text == "💰 Пополнить счет")
async def admin_topup(message: Message, state: FSMContext):
    u = await ensure_user(message.from_user)
    if u["is_admin"] != 1:
        return await message.answer("⛔ Недостаточно прав.")
    await state.clear()
    await state.set_state(AdminTopUpAccount.account)
    await message.answer("Введите счет: capital или investor:ilya / investor:mikhail")


@dp.message(AdminTopUpAccount.account)
async def admin_topup_account(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    await state.update_data(account=message.text.strip())
    await state.set_state(AdminTopUpAccount.amount)
    await message.answer("Введите сумму (число).")


@dp.message(AdminTopUpAccount.amount)
async def admin_topup_amount(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    try:
        amount = parse_money(message.text)
    except Exception:
        return await message.answer("Введите число.")
    await state.update_data(amount=amount)
    await state.set_state(AdminTopUpAccount.reason)
    await message.answer("Введите причину (можно '-')")


@dp.message(AdminTopUpAccount.reason)
async def admin_topup_reason(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    data = await state.get_data()
    acc = data["account"]
    amt = float(data["amount"])
    reason = message.text.strip()
    await DBH.create_transaction(date.today().isoformat(), None, acc, amt, f"TOPUP: {reason}", None, message.from_user.id)
    await state.clear()
    await message.answer("✅ Пополнено.")


# ============================
# Finance - accounts
# ============================
@dp.message(F.text == "💳 Счета")
async def accounts(message: Message):
    await ensure_user(message.from_user)
    cap = await DBH.get_account_balance("capital")
    lines = [f"Капитал: {cap:.2f}"]
    for inv in CFG.get("investors", {}).get("list", []):
        bal = await DBH.get_account_balance(f"investor:{inv['id']}")
        lines.append(f"{inv['name']}: {bal:.2f}")
    await message.answer("\n".join(lines))


# ============================
# Finance - create deal
# ============================
@dp.message(F.text == "➕ Сделка")
async def add_deal(message: Message, state: FSMContext):
    u = await ensure_user(message.from_user)
    if u["is_member"] != 1 and u["is_admin"] != 1:
        return await message.answer("⛔ Недостаточно прав.")
    await state.clear()
    await state.set_state(DealCreate.date)
    await message.answer("📅 Дата сделки\n1. сегодня\n2. вчера\n\nИли впишите в формате: 09.12.2026")


@dp.message(DealCreate.date)
async def deal_date(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    try:
        d = parse_date(message.text)
    except Exception:
        return await message.answer("⛔ Неверная дата.")
    await state.update_data(created_at=d)
    await state.set_state(DealCreate.funding)
    await message.answer("💰 Источник денег (цифра):\n1. Капитал\n2. Инвестор\n3. Долг")


@dp.message(DealCreate.funding)
async def deal_funding(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    t = message.text.strip()
    if t not in ("1", "2", "3"):
        return await message.answer("Введите 1 / 2 / 3.")
    funding = {"1": "capital", "2": "investor", "3": "loan"}[t]
    await state.update_data(funding_source=funding)

    if funding in ("investor", "loan"):
        invs = CFG.get("investors", {}).get("list", [])
        opts = [f"{inv['name']} ({inv['id']})" for inv in invs]
        await state.set_state(DealCreate.investor_pick)
        await message.answer(choice_list("👤 Выберите инвестора (цифра):", opts))
    else:
        await state.set_state(DealCreate.list_price)
        await message.answer("🏷 Цена в объявлении (число).")


@dp.message(DealCreate.investor_pick)
async def deal_pick_investor(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    invs = CFG.get("investors", {}).get("list", [])
    try:
        idx = int(message.text.strip())
        if idx < 1 or idx > len(invs):
            raise ValueError()
    except Exception:
        return await message.answer("Введите номер из списка.")
    investor_id = invs[idx-1]["id"]
    await state.update_data(investor_id=investor_id)

    data = await state.get_data()
    if data["funding_source"] == "loan":
        await state.set_state(DealCreate.loan_interest)
        await message.answer("📈 Процент по долгу (единоразово), например 0 или 5.")
    else:
        await state.set_state(DealCreate.list_price)
        await message.answer("🏷 Цена в объявлении (число).")


@dp.message(DealCreate.loan_interest)
async def deal_loan_interest(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    try:
        p = parse_money(message.text)
        if p < 0:
            raise ValueError()
    except Exception:
        return await message.answer("Введите число >= 0.")
    await state.update_data(loan_interest=p)
    await state.set_state(DealCreate.loan_due)
    await message.answer("📅 Срок возврата долга\n1. сегодня\n2. вчера\n\nИли впишите в формате: 09.12.2026")


@dp.message(DealCreate.loan_due)
async def deal_loan_due(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    try:
        d = parse_date(message.text)
    except Exception:
        return await message.answer("⛔ Неверная дата.")
    await state.update_data(loan_due=d)
    await state.set_state(DealCreate.list_price)
    await message.answer("🏷 Цена в объявлении (число).")


@dp.message(DealCreate.list_price)
async def deal_list_price(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    try:
        lp = parse_money(message.text)
    except Exception:
        return await message.answer("Введите число.")
    await state.update_data(list_price=lp)
    await state.set_state(DealCreate.buy_price)
    await message.answer("💵 Фактическая цена покупки (число).")


@dp.message(DealCreate.buy_price)
async def deal_buy_price(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    try:
        bp = parse_money(message.text)
    except Exception:
        return await message.answer("Введите число.")
    data = await state.get_data()
    bargain = max(0.0, float(data["list_price"]) - bp)
    await state.update_data(buy_price=bp, bargain_amount=bargain)
    await state.set_state(DealCreate.deal_type)
    await message.answer(
        "🧾 Выберите тип сделки (цифра):\n"
        "1. Перепродажа\n"
        "2. Под ремонт\n"
        "3. Сборка ПК (проект)\n"
        "4. Услуга: сборка\n"
        "5. Услуга: диагностика"
    )


@dp.message(DealCreate.deal_type)
async def deal_type(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    mapping = {"1": "resale", "2": "repair", "3": "pc_build_project", "4": "service_build", "5": "service_diagnostic"}
    t = message.text.strip()
    if t not in mapping:
        return await message.answer("Введите 1..5.")
    await state.update_data(deal_type=mapping[t], status="bought")
    await state.set_state(DealCreate.notes)
    await message.answer("📝 Комментарий (можно '-')")


@dp.message(DealCreate.notes)
async def deal_notes(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    txt = message.text.strip()
    await state.update_data(notes=None if txt == "-" else txt)
    await state.set_state(DealCreate.location)
    await message.answer(
        "📍 Где находится товар? (цифра)\n"
        "1. Основной склад\n"
        "2. Стас\n"
        "3. Илья\n"
        "4. Данило\n"
        "5. Лёня\n"
        "6. Другое"
    )


@dp.message(DealCreate.location)
async def deal_location(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    t = message.text.strip()
    mapping = {"1": "Основной склад", "2": "Стас", "3": "Илья", "4": "Данило", "5": "Лёня"}
    if t in mapping:
        await state.update_data(location_holder=mapping[t])
        await state.set_state(DealCreate.items)
    elif t == "6":
        await state.set_state(DealCreate.location_text)
        return await message.answer("Введите локацию текстом (например: Другое: у Пети).")
    else:
        # allow free text too
        await state.update_data(location_holder=t)
        await state.set_state(DealCreate.items)

    cats = ", ".join(CFG.get("subcategories", {}).get("allowed", []))
    await message.answer(
        "📦 Введите позиции (можно несколькими строками сразу), формат:\nGPU:RTX4070:50000\n\n"
        f"Категории:\n{cats}\n\n"
        "Когда закончите — напишите: 1."
    )


@dp.message(DealCreate.location_text)
async def deal_location_text(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    await state.update_data(location_holder=message.text.strip())
    await state.set_state(DealCreate.items)
    cats = ", ".join(CFG.get("subcategories", {}).get("allowed", []))
    await message.answer(
        "📦 Введите позиции (можно несколькими строками сразу), формат:\nGPU:RTX4070:50000\n\n"
        f"Категории:\n{cats}\n\n"
        "Когда закончите — напишите: 1."
    )


@dp.message(DealCreate.items)
async def deal_items(message: Message, state: FSMContext):
    await ensure_user(message.from_user)
    data = await state.get_data()
    allowed = CFG.get("subcategories", {}).get("allowed", [])
    items = data.get("items", [])

    lines = parse_lines(message.text)
    finish = {"1", "1.", "ГОТОВО", "готово"}
    done = any(ln.strip() in finish or ln.strip().upper() in {x.upper() for x in finish} for ln in lines)

    def items_list_text(it_list: List[Dict[str, Any]]) -> str:
        if not it_list:
            return "—"
        out = []
        for i, it in enumerate(it_list, start=1):
            out.append(f"{i}. [{it['subcategory']}] {it['title']} — {int(float(it['estimate_before']))}р")
        return "\n".join(out)

    for ln in lines:
        raw = ln.strip()
        up = raw.upper()
        if raw in finish or up in {x.upper() for x in finish}:
            continue

        # delete: -N
        mdel = re.match(r"^-\s*(\d+)$", raw)
        if mdel:
            idx = int(mdel.group(1))
            if 1 <= idx <= len(items):
                items.pop(idx - 1)
            else:
                return await message.answer(f"⛔ Нет позиции с номером {idx}.\nТекущие позиции:\n{items_list_text(items)}")
            continue

        # edit: N=...
        medit = re.match(r"^(\d+)\s*=\s*(.+)$", raw)
        if medit:
            idx = int(medit.group(1))
            if not (1 <= idx <= len(items)):
                return await message.answer(f"⛔ Нет позиции с номером {idx}.\nТекущие позиции:\n{items_list_text(items)}")
            try:
                it = item_from_line(medit.group(2), allowed)
            except Exception as e:
                return await message.answer(f"⛔ Ошибка в правке позиции {idx}: {e}")
            items[idx - 1] = it
            continue

        try:
            items.append(item_from_line(raw, allowed))
        except Exception as e:
            return await message.answer(f"⛔ Ошибка в строке '{raw}': {e}")

    await state.update_data(items=items)

    if not done:
        return await message.answer(
            f"✅ Принято. Сейчас позиций: {len(items)}\n"
            f"{items_list_text(items)}\n\n"
            "Добавьте ещё строки, или редактируйте (-N / N=...), или завершите цифрой 1."
        )

    if not items:
        return await message.answer("⛔ Нужна хотя бы 1 позиция (затем 1).")

    created_at = data["created_at"]
    funding = data["funding_source"]
    investor_id = data.get("investor_id")
    buy_price = float(data["buy_price"])

    loan_id = None
    if funding == "loan":
        loan_id = await DBH.create_loan(investor_id, buy_price, float(data.get("loan_interest", 0.0)), data["loan_due"])
        # principal: investor -> capital, then purchase from capital
        await DBH.create_transaction(created_at, f"investor:{investor_id}", "capital", buy_price, f"Долг: получена сумма (loan#{loan_id})", None, message.from_user.id)
        await DBH.create_transaction(created_at, "capital", None, buy_price, "Покупка (долг)", None, message.from_user.id)
    elif funding == "investor":
        await DBH.create_transaction(created_at, f"investor:{investor_id}", None, buy_price, "Покупка (на деньги инвестора)", None, message.from_user.id)
    else:
        await DBH.create_transaction(created_at, "capital", None, buy_price, "Покупка (капитал)", None, message.from_user.id)

    deal_id = await DBH.create_deal({
        "created_at": created_at,
        "status": "bought",
        "deal_type": data["deal_type"],
        "funding_source": funding,
        "investor_id": investor_id,
        "loan_id": loan_id,
        "list_price": float(data["list_price"]),
        "buy_price": buy_price,
        "bargain_amount": float(data["bargain_amount"]),
        "notes": data.get("notes"),
        "location_holder": data.get("location_holder"),
        "last_listing_update": None
    })

    for it in items:
        await DBH.add_deal_item(deal_id, it)

    await state.clear()
    await message.answer(f"✅ Сделка создана: #{deal_id}\nТорг: {float(data['bargain_amount']):.2f}\nПозиций: {len(items)}")

    # notify members (regular)
    recipients = await DBH.list_admins_and_members()
    drow = await DBH.get_deal(deal_id)
    for r in recipients:
        if r["mute_regular"] == 1:
            continue
        if drow:
            await send_message_safe(r["tg_id"], f"🆕 Создана сделка {await deal_line(drow)}")


# ============================
# TODO: For brevity in this v8 file, only deal creation is included.
# The previous v6 feature-set (closing deals, payouts, loans UI, etc.) can be merged once this base is stable.
# ============================


# ============================
# Additional handlers (v9 patch for v8 base)
# ============================

def _ru_status(s: str) -> str:
    return {"bought": "Куплен", "sold": "Продан", "return": "Возврат"}.get(s, s)


def _required_task_keys(dt: str) -> List[str]:
    if dt == "service_build":
        return list(CFG["tasks"]["service_build"].keys())
    if dt == "service_diagnostic":
        return list(CFG["tasks"]["service_diagnostic"].keys())
    if dt == "repair":
        return list(CFG["tasks"]["repair"].keys())
    return list(CFG["tasks"]["resale"].keys())


async def _db_rows(sql: str, params: Tuple[Any, ...] = ()) -> List[aiosqlite.Row]:
    async with DBH.connect() as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(sql, params)
        return await cur.fetchall()


async def _db_row(sql: str, params: Tuple[Any, ...] = ()) -> Optional[aiosqlite.Row]:
    rows = await _db_rows(sql, params)
    return rows[0] if rows else None


# ---------- Expenses ----------
@dp.message(F.text == "➕ Расход")
async def add_expense(message: Message, state: FSMContext):
    u = await ensure_user(DBH, CFG, message.from_user)
    if u["is_member"] != 1 and u["is_admin"] != 1:
        return await message.answer("⛔ Недостаточно прав.")
    await state.clear()
    await state.set_state(ExpenseCreate.amount)
    await message.answer("💸 Сумма расхода (число)")


@dp.message(ExpenseCreate.amount)
async def exp_amount(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    try:
        amt = parse_money(message.text)
    except Exception:
        return await message.answer("Введите число.")
    await state.update_data(amount=amt)
    await state.set_state(ExpenseCreate.date)
    await message.answer("📅 Дата расхода\n1. сегодня\n2. вчера\n\nИли впишите в формате: 09.12.2026")


@dp.message(ExpenseCreate.date)
async def exp_date(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    try:
        d = parse_date(message.text)
    except Exception:
        return await message.answer("⛔ Неверная дата.")
    await state.update_data(date=d)
    await state.set_state(ExpenseCreate.exp_type)
    await message.answer("🧾 Тип расхода:\n1. Проезд/бензин\n2. Расходники\n3. Другое")


@dp.message(ExpenseCreate.exp_type)
async def exp_type(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    m = {"1": "Проезд/бензин", "2": "Расходники", "3": "Другое"}
    t = message.text.strip()
    if t not in m:
        return await message.answer("Введите 1..3.")
    await state.update_data(exp_type=m[t])
    await state.set_state(ExpenseCreate.description)
    await message.answer("📝 Описание (можно '-')")


@dp.message(ExpenseCreate.description)
async def exp_desc(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    txt = message.text.strip()
    await state.update_data(description=None if txt == "-" else txt)
    await state.set_state(ExpenseCreate.relate)
    await message.answer("Относится к сделке?\n1. Да\n2. Нет")


@dp.message(ExpenseCreate.relate)
async def exp_relate(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    t = message.text.strip()
    if t not in ("1", "2"):
        return await message.answer("Введите 1 или 2.")
    data = await state.get_data()
    if t == "2":
        await DBH.add_expense({
            "date": data["date"],
            "amount": float(data["amount"]),
            "exp_type": data["exp_type"],
            "description": data.get("description"),
            "deal_id": None,
            "created_by": message.from_user.id
        })
        await DBH.create_transaction(data["date"], "capital", None, float(data["amount"]), f"Расход: {data['exp_type']}", None, message.from_user.id)
        await state.clear()
        return await message.answer("✅ Расход добавлен (не привязан к сделке).")

    deals = await DBH.list_recent_deals(10)
    await state.set_state(ExpenseCreate.pick_deal)
    await message.answer("Выберите сделку:", reply_markup=await inline_deals(deals, "expsel"))


@dp.callback_query(F.data.startswith("expsel:"))
async def exp_pick_deal(cb: CallbackQuery, state: FSMContext):
    await ensure_user(DBH, CFG, cb.from_user)
    if cb.data.endswith(":back"):
        await cb.answer()
        return
    deal_id = int(cb.data.split(":")[1])
    data = await state.get_data()
    await DBH.add_expense({
        "date": data["date"],
        "amount": float(data["amount"]),
        "exp_type": data["exp_type"],
        "description": data.get("description"),
        "deal_id": deal_id,
        "created_by": cb.from_user.id
    })
    await DBH.create_transaction(data["date"], "capital", None, float(data["amount"]), f"Расход (deal#{deal_id}): {data['exp_type']}", deal_id, cb.from_user.id)
    await state.clear()
    await cb.message.answer(f"✅ Расход добавлен к сделке #{deal_id}.")
    await cb.answer()


# ---------- Status deal -> add deal task ----------
@dp.message(F.text == "📌 Статус сделки")
async def status_pick(message: Message):
    await ensure_user(DBH, CFG, message.from_user)
    deals = await DBH.list_recent_deals(15)
    if not deals:
        return await message.answer("Нет сделок.")
    await message.answer("Выберите сделку:", reply_markup=await inline_deals(deals, "statusdeal"))


@dp.callback_query(F.data.startswith("statusdeal:"))
async def status_deal(cb: CallbackQuery, state: FSMContext):
    await ensure_user(DBH, CFG, cb.from_user)
    if cb.data.endswith(":back"):
        await cb.answer()
        return
    deal_id = int(cb.data.split(":")[1])
    d = await DBH.get_deal(deal_id)
    if not d:
        await cb.answer("Не найдено", show_alert=True)
        return
    keys = _required_task_keys(d["deal_type"])
    await state.clear()
    await state.update_data(deal_id=deal_id)
    await cb.message.answer("Выберите задачу:", reply_markup=inline_tasks(deal_id, keys))
    await cb.answer()


@dp.callback_query(F.data.startswith("taskpick:"))
async def taskpick(cb: CallbackQuery, state: FSMContext):
    await ensure_user(DBH, CFG, cb.from_user)
    _, deal_id_s, task_key = cb.data.split(":")
    deal_id = int(deal_id_s)
    # запрет задачи 'Ремонт' для сделок не типа 'Под ремонт'
    d = await DBH.get_deal(deal_id)
    if d and task_key == "repair" and d.get("deal_type") != "repair":
        await cb.answer("Ремонт доступен только для сделок 'Под ремонт'.", show_alert=True)
        return

    if task_key == "back":
        deals = await DBH.list_recent_deals(15)
        await cb.message.answer("Выберите сделку:", reply_markup=await inline_deals(deals, "statusdeal"))
        await cb.answer()
        return

    async with DBH.connect() as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute(
            "SELECT * FROM deal_tasks WHERE deal_id=? AND task_type=? ORDER BY task_id DESC LIMIT 1",
            (deal_id, task_key),
        )
        existing = await cur.fetchone()

    if existing:
        task_id = int(existing["task_id"])
        async with DBH.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute(
                """
                SELECT COALESCE(u.display_name, u.full_name, u.username, u.tg_id) AS name
                FROM deal_task_performers p
                JOIN users u ON u.tg_id=p.performer_id
                WHERE p.task_id=?
                """,
                (task_id,),
            )
            pr = await cur.fetchall()

        perf_txt = ", ".join([str(r["name"]) for r in pr]) if pr else "—"
        comp = existing["complexity"] or "—"
        comp_map = {
            "detail": "Деталь",
            "project": "Проект",
            "pvz": "ПВЗ/Лично",
            "own_delivery": "Доставка своими силами",
            "repair_high": "Сложный",
            "repair_mid": "Средний",
            "repair_low": "Низкий",
            "usual": "Как обычно",
            "long": "Долго",
        }
        comp = comp_map.get(comp, comp)
        ai = float(existing["ai_mult"] or 1.0)
        ai_pct = f"{int(ai*100)}%"
        done_date = existing["done_date"] or "—"

        txt = (
            f"✅ Значения уже есть по задаче: {TASK_LABEL.get(task_key, task_key)}\n"
            f"Сделка: #{deal_id}\n"
            f"Исполнители: {perf_txt}\n"
            f"Сложность/тип: {comp}\n"
            f"ИИ: {ai_pct}\n"
            f"Дата: {done_date}"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1. Посмотреть комментарий", callback_data=f"taskexist:{task_id}:comment")],
            [InlineKeyboardButton(text="2. Изменить", callback_data=f"taskexist:{task_id}:edit")],
            [InlineKeyboardButton(text="3. Удалить значения", callback_data=f"taskexist:{task_id}:delete")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="taskexist:back")]
        ])
        await cb.message.answer(txt, reply_markup=kb)
        await cb.answer()
        return

    await state.clear()
    await state.update_data(deal_id=deal_id, task_type=task_key)
    msg, mapping = await members_numbered(DBH)
    await state.update_data(member_map=mapping)
    await state.set_state(DealTaskAdd.pick_performers)
    await cb.message.answer(msg)
    await cb.answer()



@dp.message(DealTaskAdd.pick_performers)
async def deal_task_performers(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    data = await state.get_data()
    mapping = data["member_map"]
    try:
        perf_ids = parse_choice_ids(message.text, mapping)
    except Exception as e:
        return await message.answer(f"⛔ {e}")
    await state.update_data(performer_ids=perf_ids)

    d = await DBH.get_deal(int(data["deal_id"]))
    if not d:
        await state.clear()
        return await message.answer("⛔ Сделка не найдена.")

    dt = d["deal_type"]
    if dt == "service_build":
        cfg_task = CFG["tasks"]["service_build"].get(data["task_type"], {})
    elif dt == "service_diagnostic":
        cfg_task = CFG["tasks"]["service_diagnostic"].get(data["task_type"], {})
    elif dt == "repair":
        cfg_task = CFG["tasks"]["repair"].get(data["task_type"], {})
    else:
        cfg_task = CFG["tasks"]["resale"].get(data["task_type"], {})

    await state.update_data(task_cfg=cfg_task)

    task_type = data.get("task_type")
    uses_complexity = task_type in ("list", "sell", "repair", "execute", "test")
    uses_ai = bool(cfg_task.get("uses_ai", False))

    # сложность/тип — только для указанных задач
    if uses_complexity:
        await state.set_state(DealTaskAdd.complexity)
        if task_type == "list":
            return await message.answer("""Выставил:
1. Деталь
2. Проект""")
        if task_type == "sell":
            return await message.answer("""Продал:
1. ПВЗ/Лично
2. Доставка своими силами""")
        if task_type == "repair":
            return await message.answer("""Ремонт:
1. Сложный
2. Средний
3. Низкий""")
        if task_type == "execute":
            return await message.answer("""Обслуживание:
1. Как обычно
2. Долго""")
        if task_type == "test":
            return await message.answer("""Тест/Обслуживание:
1. Только тест
2. Обслуживание + тест""")

    # множитель ИИ берём из конфига (пользователь не выбирает)
    if uses_ai:
        ai_mult = float(CFG.get("ai", {}).get("multiplier", 1.0))
        await state.update_data(ai_mult=ai_mult)

    await state.set_state(DealTaskAdd.comment)
    await message.answer("Комментарий (можно '-')")



@dp.message(DealTaskAdd.complexity)
async def deal_task_complexity(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    data = await state.get_data()
    task_type = data.get("task_type")
    t = message.text.strip()

    if task_type == "list":
        m = {"1": "detail", "2": "project"}
        if t not in m:
            return await message.answer("Введите 1 или 2.")
        await state.update_data(complexity=m[t])
    elif task_type == "sell":
        m = {"1": "pvz", "2": "own_delivery"}
        if t not in m:
            return await message.answer("Введите 1 или 2.")
        await state.update_data(complexity=m[t])
    elif task_type == "repair":
        m = {"1": "repair_high", "2": "repair_mid", "3": "repair_low"}
        if t not in m:
            return await message.answer("Введите 1..3.")
        await state.update_data(complexity=m[t])
    elif task_type == "execute":
        m = {"1": "usual", "2": "long"}
        if t not in m:
            return await message.answer("Введите 1 или 2.")
        await state.update_data(complexity=m[t])
    elif task_type == "test":
        m = {"1": "test_only", "2": "service_test"}
        if t not in m:
            return await message.answer("Введите 1 или 2.")
        await state.update_data(complexity=m[t])
    else:
        # для остальных задач сложность не используется
        await state.update_data(complexity=None)

    cfg_task = (await state.get_data()).get("task_cfg", {})
    if cfg_task.get("uses_ai", False):
        ai_mult = float(CFG.get("ai", {}).get("multiplier", 1.0))
        await state.update_data(ai_mult=ai_mult)

    await state.set_state(DealTaskAdd.comment)
    await message.answer("Комментарий (можно '-')")



@dp.message(DealTaskAdd.ai_mult)
async def deal_task_ai(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    m = {"1": 0.0, "2": 0.5, "3": 1.0}
    t = message.text.strip()
    if t not in m:
        return await message.answer("Введите 1..3.")
    await state.update_data(ai_mult=m[t])
    await state.set_state(DealTaskAdd.comment)
    await message.answer("Комментарий (можно '-')")


@dp.message(DealTaskAdd.comment)
async def deal_task_comment(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    txt = message.text.strip()
    await state.update_data(comment=None if txt == "-" else txt)
    await state.set_state(DealTaskAdd.done_date)
    await message.answer("📅 Дата выполнения\n1. сегодня\n2. вчера\n\nИли: 09.12.2026")


@dp.message(DealTaskAdd.done_date)
async def deal_task_done_date(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    try:
        d = parse_date(message.text)
    except Exception:
        return await message.answer("⛔ Неверная дата.")
    data = await state.get_data()
    task_id = await DBH.create_deal_task({
        "deal_id": int(data["deal_id"]),
        "task_type": data["task_type"],
        "complexity": data.get("complexity"),
        "ai_mult": float(data.get("ai_mult", 1.0)),
        "comment": data.get("comment"),
        "done_date": d,
        "created_by": message.from_user.id,
    }, data["performer_ids"])
    await state.clear()
    await message.answer(f"✅ Задача записана (task#{task_id})")



@dp.callback_query(F.data.startswith("taskexist:"))
async def taskexist(cb: CallbackQuery, state: FSMContext):
    await ensure_user(DBH, CFG, cb.from_user)

    if cb.data == "taskexist:back":
        deals = await DBH.list_recent_deals(15)
        await cb.message.answer("Выберите сделку:", reply_markup=await inline_deals(deals, "statusdeal"))
        await cb.answer()
        return

    _, task_id_s, action = cb.data.split(":")
    task_id = int(task_id_s)

    async with DBH.connect() as con:
        con.row_factory = aiosqlite.Row
        cur = await con.execute("SELECT * FROM deal_tasks WHERE task_id=?", (task_id,))
        trow = await cur.fetchone()

    if not trow:
        await cb.answer("Не найдено", show_alert=True)
        return

    deal_id = int(trow["deal_id"])
    task_type = trow["task_type"]

    if action == "comment":
        comment = trow["comment"] or "—"
        await cb.message.answer(f"📝 Комментарий по задаче {TASK_LABEL.get(task_type, task_type)} (deal#{deal_id}):\n{comment}")
        await cb.answer()
        return

    if action == "delete":
        async with DBH.connect() as con:
            await con.execute("DELETE FROM deal_task_performers WHERE task_id=?", (task_id,))
            await con.execute("DELETE FROM deal_tasks WHERE task_id=?", (task_id,))
            await con.commit()
        await cb.message.answer("✅ Значения удалены.")
        await cb.answer()
        return

    if action == "edit":
        async with DBH.connect() as con:
            await con.execute("DELETE FROM deal_task_performers WHERE task_id=?", (task_id,))
            await con.execute("DELETE FROM deal_tasks WHERE task_id=?", (task_id,))
            await con.commit()

        await state.clear()
        await state.update_data(deal_id=deal_id, task_type=task_type)
        msg, mapping = await members_numbered(DBH)
        await state.update_data(member_map=mapping)
        await state.set_state(DealTaskAdd.pick_performers)
        await cb.message.answer("✏️ Введите новые значения.\n" + msg)
        await cb.answer()
        return

    await cb.answer()
# ---------- Close deal ----------
@dp.message(F.text == "✅ Закрыть сделку")
async def close_start(message: Message, state: FSMContext):
    u = await ensure_user(DBH, CFG, message.from_user)
    if u["is_member"] != 1 and u["is_admin"] != 1:
        return await message.answer("⛔ Недостаточно прав.")
    deals = await DBH.list_recent_open_deals(15)
    if not deals:
        return await message.answer("Нет активных сделок.")
    await state.clear()
    await state.set_state(CloseDeal.pick_deal)
    await message.answer("Выберите сделку:", reply_markup=await inline_deals(deals, "closedeal"))


@dp.callback_query(F.data.startswith("closedeal:"))
async def close_pick(cb: CallbackQuery, state: FSMContext):
    await ensure_user(DBH, CFG, cb.from_user)
    if cb.data.endswith(":back"):
        await cb.answer()
        return
    deal_id = int(cb.data.split(":")[1])
    d = await DBH.get_deal(deal_id)
    if not d:
        await cb.answer("Не найдено", show_alert=True)
        return
    required = set(_required_task_keys(d["deal_type"]))
    done = set(await DBH.done_task_types(deal_id))
    missing = sorted(list(required - done))
    if missing:
        miss_txt = "\n".join([f"- {TASK_LABEL.get(k,k)}" for k in missing])
        await cb.message.answer(f"⛔ Нельзя закрыть сделку #{deal_id}: не закрыты все задачи.\n\nНе хватает:\n{miss_txt}")
        await cb.answer()
        return
    await state.clear()
    await state.set_state(CloseDeal.outcome)
    await state.update_data(deal_id=deal_id)
    await cb.message.answer("Результат:\n1. 🔴 Продано\n2. 🟡 Возврат")
    await cb.answer()


@dp.message(CloseDeal.outcome)
async def close_outcome(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    t = message.text.strip()
    if t not in ("1", "2"):
        return await message.answer("Введите 1 или 2.")

    data = await state.get_data()
    deal_id = int(data["deal_id"])
    d = await DBH.get_deal(deal_id)
    if not d:
        await state.clear()
        return await message.answer("⛔ Сделка не найдена.")

    if t == "2":
        await state.set_state(CloseDeal.return_refund)
        return await message.answer(
            f"🟡 Возврат.\nВведите сумму возврата (число) или '-' если вернули полностью ({float(d['buy_price']):.2f})."
        )

    items = await DBH.list_deal_items(deal_id)
    if not items:
        await state.clear()
        return await message.answer("⛔ У сделки нет позиций.")

    await state.set_state(CloseDeal.sale_input)
    await state.update_data(items=[dict(x) for x in items])

    lines = ["📦 Позиции:"]
    for i, it in enumerate(items, start=1):
        lines.append(f"{i}. [{it['subcategory']}] {it['title']} (ID {it['item_id']})")
    lines.append("")
    lines.append("")
    lines.append("Введите продажи строками (в том же порядке):")
    lines.append("Формат: цена;дата;доставка;комиссия%")
    lines.append("- Пример: 25000;сегодня;avito;7")
    await message.answer("\n".join(lines))



@dp.message(CloseDeal.return_refund)
async def close_return(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    data = await state.get_data()
    deal_id = int(data["deal_id"])
    d = await DBH.get_deal(deal_id)
    if not d:
        await state.clear()
        return await message.answer("⛔ Сделка не найдена.")
    txt = message.text.strip()
    if txt == "-":
        refund = float(d["buy_price"])
    else:
        try:
            refund = parse_money(txt)
        except Exception:
            return await message.answer("Введите число или '-'.")
    await DBH.create_transaction(date.today().isoformat(), None, "capital", refund, "Возврат покупки (деньги вернули)", deal_id, message.from_user.id)
    await DBH.close_deal(deal_id, "return", date.today().isoformat())
    await state.clear()
    await message.answer(f"✅ Сделка #{deal_id} закрыта: 🟡 Возврат.\nСумма: {refund:.2f}")


def _task_weight(cfg_task: Dict[str, Any], complexity: Optional[str], ai_mult: float) -> float:
    w = float(cfg_task.get("base_weight", 0))
    if cfg_task.get("uses_complexity") or ttype in ("list", "sell", "repair", "execute"):
        w *= complexity_mult(CFG, complexity)
    if cfg_task.get("uses_ai"):
        w *= float(ai_mult)
    return w


@dp.message(CloseDeal.sale_input)
async def close_sale(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    data = await state.get_data()
    deal_id = int(data["deal_id"])
    items: List[Dict[str, Any]] = data["items"]
    lines_in = parse_lines(message.text)

    if len(lines_in) != len(items):
        return await message.answer(f"⛔ Нужно {len(items)} строк(и) (по одной на позицию).")

    gross = 0.0
    fee_total = 0.0
    for idx, ln in enumerate(lines_in):
        try:
            price, sdate, delivery, fee_percent = parse_sale_line(ln)
        except Exception as e:
            return await message.answer(f"⛔ {e}")
        it = items[idx]
        await DBH.update_item_sale(int(it["item_id"]), price, sdate, delivery, fee_percent)
        gross += price
        fee_total += price * fee_percent / 100.0

    # Авто-расход на комиссию
    if fee_total > 0:
        await DBH.add_expense({
            "date": date.today().isoformat(),
            "amount": fee_total,
            "exp_type": "Комиссия доставки",
            "description": "Автоматически (по % доставки/сервиса)",
            "deal_id": deal_id,
            "created_by": message.from_user.id
        })

    d = await DBH.get_deal(deal_id)
    if not d:
        await state.clear()
        return await message.answer("⛔ Сделка не найдена.")

    # Проценты по долгу как расход
    if d["funding_source"] == "loan" and d["loan_id"]:
        loan = await DBH.get_loan(int(d["loan_id"]))
        if loan:
            interest = float(loan["principal"]) * float(loan["interest_percent"]) / 100.0
            if interest > 0:
                await DBH.add_expense({
                    "date": date.today().isoformat(),
                    "amount": interest,
                    "exp_type": "Проценты по долгу",
                    "description": f"Автоматически (loan#{loan['loan_id']})",
                    "deal_id": deal_id,
                    "created_by": message.from_user.id
                })

    expenses_total = await DBH.sum_expenses_for_deal(deal_id)
    buy_price = float(d["buy_price"])
    profit = gross - buy_price - expenses_total

    # Деньги в капитал (нетто после комиссии)
    net_in = max(0.0, gross - fee_total)
    await DBH.create_transaction(date.today().isoformat(), None, "capital", net_in, "Выручка (нетто после комиссий)", deal_id, message.from_user.id)

    # Возврат тела инвестору
    if d["funding_source"] == "investor" and d["investor_id"]:
        await DBH.create_transaction(date.today().isoformat(), "capital", f"investor:{d['investor_id']}", buy_price, "Возврат закупки инвестору (тело)", deal_id, message.from_user.id)

    await DBH.close_deal(deal_id, "sold", date.today().isoformat())

    # ===== Расчёт выплат =====
    cap_cash_before = await DBH.get_account_balance("capital")
    cap_rate = cap_rate_for_balance(CFG, cap_cash_before)
    cap_cut = max(0.0, profit * cap_rate)

    inv_cut = 0.0
    is_service = d["deal_type"] in ("service_build", "service_diagnostic")
    if (not is_service) and d["funding_source"] == "investor" and d["investor_id"]:
        inv_cut = max(0.0, profit * investor_rate(CFG, d["investor_id"]))

    bargain_bonus = 0.0
    if CFG.get("bargain_bonus", {}).get("enabled", True):
        barg = float(d["bargain_amount"])
        if barg > 0 and profit > 0:
            rate = float(CFG["bargain_bonus"]["rate"])
            cap_share = float(CFG["bargain_bonus"]["cap_share_of_profit"])
            bargain_bonus = min(barg * rate, profit * cap_share)

    performer_pool = profit - cap_cut - inv_cut - bargain_bonus
    if profit <= 0:
        cap_cut = 0.0
        inv_cut = 0.0
        bargain_bonus = 0.0
        performer_pool = 0.0

    # сброс payouts
    async with DBH.connect() as con:
        await con.execute("DELETE FROM payouts WHERE deal_id=?", (deal_id,))
        await con.commit()

    payouts_total = 0.0

    if inv_cut > 0 and d["investor_id"]:
        inv_cut = round(inv_cut, 2)
        await DBH.create_payout(deal_id, inv_cut, kind="investor", investor_id=d["investor_id"])
        payouts_total += inv_cut
    # Доля капитала (как "выплата" для учета и закрытия)
    if cap_cut > 0:
        cap_cut = round(cap_cut, 2)
        await DBH.create_payout(deal_id, cap_cut, kind="capital")

    # веса задач
    tasks = await DBH.list_deal_tasks(deal_id)
    dt = d["deal_type"]
    if dt == "service_build":
        weights_cfg = CFG["tasks"]["service_build"]
    elif dt == "service_diagnostic":
        weights_cfg = CFG["tasks"]["service_diagnostic"]
    elif dt == "repair":
        weights_cfg = CFG["tasks"]["repair"]
    else:
        weights_cfg = CFG["tasks"]["resale"]

    task_weights: List[Tuple[int, float, List[int], str]] = []
    total_w = 0.0
    for trow in tasks:
        ttype = trow["task_type"]
        cfg_task = weights_cfg.get(ttype)
        if not cfg_task:
            continue
        w = float(cfg_task.get("base_weight", 0))
        if cfg_task.get("uses_complexity") or ttype in ("list", "sell", "repair", "execute"):
            w *= complexity_mult(CFG, trow["complexity"])
        if cfg_task.get("uses_ai"):
            w *= float(trow["ai_mult"] or 1.0)
        if w <= 0:
            continue
        perf = await DBH.list_task_performers(int(trow["task_id"]))
        if not perf:
            continue
        task_weights.append((int(trow["task_id"]), w, perf, ttype))
        total_w += w

    # Пул исполнителей: нормализация по весам + округление до копеек в пользу более дорогих выплат
    if performer_pool > 0 and total_w > 0:
        total_cents = int(round(performer_pool * 100))
        raw_entries: List[Tuple[int, float]] = []
        for _task_id, w, perf_ids, _ttype in task_weights:
            share = performer_pool * (w / total_w)
            per_person = share / len(perf_ids)
            for pid in perf_ids:
                raw_entries.append((pid, per_person))

        cents = [int(raw * 100) for _, raw in raw_entries]  # floor
        used = sum(cents)
        rest = total_cents - used
        idxs = sorted(range(len(raw_entries)), key=lambda i: raw_entries[i][1], reverse=True)
        k = 0
        while rest > 0 and idxs:
            cents[idxs[k % len(idxs)]] += 1
            rest -= 1
            k += 1

        for (pid, _raw), c in zip(raw_entries, cents):
            amt = c / 100.0
            if amt <= 0:
                continue
            await DBH.create_payout(deal_id, amt, kind="performer", user_id=pid)
            payouts_total += amt

    # Бонус торга — равными долями по получателям
    if bargain_bonus > 0:
        pay_to = str(CFG.get("bargain_bonus", {}).get("pay_to_task", "acquire"))
        recipients: List[int] = []
        for _task_id, _w, perf_ids, ttype in task_weights:
            if ttype == pay_to:
                recipients.extend(perf_ids)
        if not recipients and task_weights:
            for _task_id, _w, perf_ids, _ttype in task_weights:
                recipients.extend(perf_ids)
        recipients = sorted(list(set(recipients)))
        if recipients:
            total_cents = int(round(bargain_bonus * 100))
            per_cents = total_cents // len(recipients)
            rest = total_cents - per_cents * len(recipients)
            for i, pid in enumerate(recipients):
                c = per_cents + (1 if i < rest else 0)
                amt = c / 100.0
                if amt <= 0:
                    continue
                await DBH.create_payout(deal_id, amt, kind="bargain", user_id=pid)
                payouts_total += amt

    await DBH.upsert_close_summary(deal_id, {
        "profit": profit,
        "cap_rate": cap_rate,
        "cap_cut": cap_cut,
        "inv_cut": inv_cut,
        "performer_pool": performer_pool,
        "bargain_bonus": bargain_bonus,
        "payouts_total": payouts_total
    })

    await state.clear()
    await message.answer(
        f"✅ Сделка #{deal_id} закрыта: 🔴 ПРОДАНО\n\n"
        f"- Выручка (gross): {gross:.2f}\n"
        f"- Комиссии (авто): {fee_total:.2f}\n"
        f"- Расходы (всего): {expenses_total:.2f}\n\n"
        f"- Прибыль: {profit:.2f}\n\n"
        f"Выплаты рассчитаны. Откройте: 💰 Финансы → 💸 Выплаты"
    )



@dp.message(F.text == "💸 Выплаты")
async def payouts_start(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    deals = await DBH.list_closed_deals(30)
    if not deals:
        return await message.answer("Нет закрытых сделок.")
    await state.clear()
    await state.set_state(PayoutsFlow.pick_deal)
    await message.answer("Выберите сделку (закрытые):", reply_markup=await inline_deals(deals, "payoutdeal"))


@dp.callback_query(F.data.startswith("payoutdeal:"))
async def payout_pick(cb: CallbackQuery):
    await ensure_user(DBH, CFG, cb.from_user)
    if cb.data.endswith(":back"):
        await cb.answer()
        return
    deal_id = int(cb.data.split(":")[1])
    payouts = await DBH.list_payouts(deal_id)
    if not payouts:
        await cb.message.answer("Нет выплат по этой сделке.")
        await cb.answer()
        return

    perf: Dict[int, float] = {}
    inv: Dict[str, float] = {}
    cap_amt = 0.0

    for p in payouts:
        amt = float(p["amount"] or 0)
        if amt <= 0:
            continue
        if p["kind"] in ("performer", "bargain") and p["user_id"]:
            perf[int(p["user_id"])] = perf.get(int(p["user_id"]), 0.0) + amt
        elif p["kind"] == "investor" and p["investor_id"]:
            inv[str(p["investor_id"])] = inv.get(str(p["investor_id"]), 0.0) + amt
        elif p["kind"] == "capital":
            cap_amt += amt

    lines = [f"Выплаты по сделке #{deal_id}:"]
    kb_rows: List[List[InlineKeyboardButton]] = []

    if perf:
        lines.append("")
        lines.append("👷 Исполнители:")
        for uid, amt in sorted(perf.items(), key=lambda x: -x[1]):
            urow = await DBH.get_user(uid)
            name = (urow["display_name"] or urow["full_name"] or (("@"+urow["username"]) if urow and urow["username"] else str(uid))) if urow else str(uid)
            lines.append(f"⏳ {name} = {amt:.2f}")
            kb_rows.append([InlineKeyboardButton(text=f"💳 Оплатить {name}", callback_data=f"payoutpay:{deal_id}:performer:{uid}")])

    if inv:
        lines.append("")
        lines.append("💼 Инвесторы:")
        for iid, amt in sorted(inv.items(), key=lambda x: -x[1]):
            inv_name = iid
            for it in CFG.get("investors", {}).get("list", []):
                if str(it.get("id")) == str(iid):
                    inv_name = it.get("name", iid)
                    break
            lines.append(f"⏳ {inv_name} = {amt:.2f}")
            kb_rows.append([InlineKeyboardButton(text=f"💳 Оплатить {inv_name}", callback_data=f"payoutpay:{deal_id}:investor:{iid}")])

    if cap_amt > 0:
        lines.append("")
        lines.append("🏦 Капитал:")
        lines.append(f"⏳ Капитал = {cap_amt:.2f}")
        kb_rows.append([InlineKeyboardButton(text="💳 Оплатить Капитал", callback_data=f"payoutpay:{deal_id}:capital:0")])

    kb_rows.append([InlineKeyboardButton(text="💳 Оплатить все", callback_data=f"payoutpay:{deal_id}:all:0")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="payoutpay:back")])

    await cb.message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()


@dp.callback_query(F.data.startswith("payoutpay:"))
async def payout_pay(cb: CallbackQuery):
    await ensure_user(DBH, CFG, cb.from_user)
    if cb.data == "payoutpay:back":
        await cb.answer()
        return

    parts = cb.data.split(":")
    deal_id = int(parts[1])
    scope = parts[2]
    ref = parts[3] if len(parts) > 3 else "0"

    payouts = await DBH.list_payouts(deal_id)
    unpaid = [p for p in payouts if p["is_paid"] == 0 and float(p["amount"] or 0) > 0]

    def pick(ps):
        if scope == "all":
            return ps
        if scope == "performer":
            uid = int(ref)
            return [p for p in ps if (p["kind"] in ("performer", "bargain") and p["user_id"] and int(p["user_id"]) == uid)]
        if scope == "investor":
            iid = str(ref)
            return [p for p in ps if (p["kind"] == "investor" and p["investor_id"] and str(p["investor_id"]) == iid)]
        if scope == "capital":
            return [p for p in ps if p["kind"] == "capital"]
        return []

    picked = pick(unpaid)
    if not picked:
        await cb.message.answer("Нет ожидающих выплат для выбранного получателя.")
        await cb.answer()
        return

    total = sum(float(p["amount"]) for p in picked)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить оплату", callback_data=f"payoutconfirm:{deal_id}:{scope}:{ref}:yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"payoutconfirm:{deal_id}:{scope}:{ref}:no")]
    ])
    await cb.message.answer(f"Подтвердить оплату?\n\nКол-во: {len(picked)}\nСумма: {total:.2f}", reply_markup=kb)
    await cb.answer()


@dp.callback_query(F.data.startswith("payoutconfirm:"))
async def payout_confirm(cb: CallbackQuery):
    await ensure_user(DBH, CFG, cb.from_user)
    parts = cb.data.split(":")
    deal_id = int(parts[1])
    scope = parts[2]
    ref = parts[3]
    ans = parts[4]

    if ans != "yes":
        await cb.message.answer("Отменено.")
        await cb.answer()
        return

    payouts = await DBH.list_payouts(deal_id)
    unpaid = [p for p in payouts if p["is_paid"] == 0 and float(p["amount"] or 0) > 0]

    def pick(ps):
        if scope == "all":
            return ps
        if scope == "performer":
            uid = int(ref)
            return [p for p in ps if (p["kind"] in ("performer", "bargain") and p["user_id"] and int(p["user_id"]) == uid)]
        if scope == "investor":
            iid = str(ref)
            return [p for p in ps if (p["kind"] == "investor" and p["investor_id"] and str(p["investor_id"]) == iid)]
        if scope == "capital":
            return [p for p in ps if p["kind"] == "capital"]
        return []

    picked = pick(unpaid)
    if not picked:
        await cb.message.answer("Нет ожидающих выплат.")
        await cb.answer()
        return

    total = sum(float(p["amount"]) for p in picked)

    if scope == "capital":
        # Капитал — без транзакций, просто закрываем
        pass
    elif scope == "investor":
        iid = str(ref)
        await DBH.create_transaction(date.today().isoformat(), "capital", f"investor:{iid}", total,
                                     f"Выплата инвестору (deal#{deal_id})", deal_id, cb.from_user.id)
    elif scope == "performer":
        uid = int(ref)
        urow = await DBH.get_user(uid)
        name = (urow["display_name"] or urow["full_name"] or (("@"+urow["username"]) if urow and urow["username"] else str(uid))) if urow else str(uid)
        await DBH.create_transaction(date.today().isoformat(), "capital", None, total,
                                     f"Выплата исполнителю {name} (deal#{deal_id})", deal_id, cb.from_user.id)
    else:
        inv_sum: Dict[str, float] = {}
        perf_sum: Dict[int, float] = {}
        for p in picked:
            amt = float(p["amount"])
            if p["kind"] == "investor" and p["investor_id"]:
                inv_sum[str(p["investor_id"])] = inv_sum.get(str(p["investor_id"]), 0.0) + amt
            elif p["kind"] in ("performer", "bargain") and p["user_id"]:
                perf_sum[int(p["user_id"])] = perf_sum.get(int(p["user_id"]), 0.0) + amt

        for iid, a in inv_sum.items():
            await DBH.create_transaction(date.today().isoformat(), "capital", f"investor:{iid}", a,
                                         f"Выплата инвестору (deal#{deal_id})", deal_id, cb.from_user.id)
        for uid, a in perf_sum.items():
            urow = await DBH.get_user(uid)
            name = (urow["display_name"] or urow["full_name"] or (("@"+urow["username"]) if urow and urow["username"] else str(uid))) if urow else str(uid)
            await DBH.create_transaction(date.today().isoformat(), "capital", None, a,
                                         f"Выплата исполнителю {name} (deal#{deal_id})", deal_id, cb.from_user.id)

    ids = [int(p["payout_id"]) for p in picked]
    async with DBH.connect() as con:
        q = f"UPDATE payouts SET is_paid=1, paid_at=? WHERE payout_id IN ({','.join(['?']*len(ids))})"
        await con.execute(q, (date.today().isoformat(), *ids))
        await con.commit()

    await cb.message.answer("✅ Выплаты выполнены и отмечены.")
    await cb.answer()




@dp.callback_query(F.data.startswith("loanpick:"))
async def loan_pick(cb: CallbackQuery):
    await ensure_user(DBH, CFG, cb.from_user)
    if cb.data.endswith(":back"):
        await cb.answer()
        return
    lid = int(cb.data.split(":")[1])
    loan = await DBH.get_loan(lid)
    if not loan:
        await cb.answer("Не найдено", show_alert=True)
        return
    principal = float(loan["principal"])
    pct = float(loan["interest_percent"])
    total = principal + principal * pct / 100.0
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Погасить", callback_data=f"loanpay:{lid}:pay")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="loanpay:back")]
    ])
    await cb.message.answer(f"Долг loan#{lid}\nИнвестор: {loan['investor_id']}\nСумма: {principal:.2f}\nПроцент: {pct:.2f}%\nК возврату: {total:.2f}\nСрок: {loan['due_date']}", reply_markup=kb)
    await cb.answer()


@dp.callback_query(F.data.startswith("loanpay:"))
async def loan_pay(cb: CallbackQuery):
    await ensure_user(DBH, CFG, cb.from_user)
    if cb.data == "loanpay:back":
        await cb.answer()
        return
    _, lid_s, act = cb.data.split(":")
    lid = int(lid_s)
    if act != "pay":
        await cb.answer()
        return
    loan = await DBH.get_loan(lid)
    if not loan:
        await cb.answer("Не найдено", show_alert=True)
        return
    principal = float(loan["principal"])
    pct = float(loan["interest_percent"])
    total = principal + principal * pct / 100.0
    await DBH.create_transaction(date.today().isoformat(), "capital", f"investor:{loan['investor_id']}", total, f"Погашение долга (loan#{lid})", None, cb.from_user.id)
    await DBH.close_loan_paid(lid)
    await cb.message.answer("✅ Долг погашен.")
    await cb.answer()


# ---------- Info: config & export ----------
@dp.message(F.text == "📄 Конфиг")
async def send_config(message: Message):
    await ensure_user(DBH, CFG, message.from_user)
    path = Path(os.getenv("CONFIG_PATH", "./config.txt"))
    if not path.exists():
        return await message.answer("Конфиг не найден.")
    await message.answer_document(FSInputFile(path))


@dp.message(F.text == "📤 Экспорт Excel")
async def export_excel(message: Message):
    await ensure_user(DBH, CFG, message.from_user)
    out_dir = Path(os.getenv("DATA_DIR", "./data")) / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    async def rows(sql: str, params: Tuple[Any, ...] = ()):
        async with DBH.connect() as con:
            con.row_factory = aiosqlite.Row
            cur = await con.execute(sql, params)
            return await cur.fetchall()

    files: List[Path] = []

    # Покупки (сделки + позиции)
    p = out_dir / f"Покупки_{ts}.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Сделки"
    ws.append(["ID сделки", "Дата", "Дата закрытия", "Статус", "Тип", "Источник", "Инвестор", "Цена в объявлении", "Цена покупки", "Торг", "Локация", "Комментарий"])
    for d in await rows("SELECT * FROM deals ORDER BY deal_id DESC"):
        ws.append([
            int(d["deal_id"]), str(d["created_at"]), str(d["closed_at"] or ""), str(d["status"]),
            str(DEAL_TYPE_LABEL.get(d["deal_type"], d["deal_type"])),
            str(d["funding_source"]), str(d["investor_id"] or ""),
            float(d["list_price"] or 0), float(d["buy_price"] or 0), float(d["bargain_amount"] or 0),
            str(d["location_holder"] or ""), str(d["notes"] or "")
        ])
    ws2 = wb.create_sheet("Позиции")
    ws2.append(["ID позиции", "ID сделки", "Категория", "Подкатегория", "Название", "Оценка (до)", "Прогноз (после)", "Цена продажи", "Дата продажи", "Доставка", "Комиссия %"])
    for it in await rows("SELECT * FROM deal_items ORDER BY item_id DESC"):
        ws2.append([
            int(it["item_id"]), int(it["deal_id"]), str(it["category"]), str(it["subcategory"]), str(it["title"]),
            it["estimate_before"], it["forecast_after"], it["sell_price"], it["sell_date"], it["delivery_type"], it["fee_percent"]
        ])
    wb.save(p)
    files.append(p)

    # Расходы
    p = out_dir / f"Расходы_{ts}.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Расходы"
    ws.append(["ID", "Дата", "Сумма", "Тип", "Описание", "ID сделки", "Кто добавил"])
    for e in await rows("SELECT * FROM expenses ORDER BY expense_id DESC"):
        ws.append([int(e["expense_id"]), str(e["date"]), float(e["amount"] or 0), str(e["exp_type"]), str(e["description"] or ""), str(e["deal_id"] or ""), str(e["created_by"] or "")])
    wb.save(p)
    files.append(p)

    # Все транзакции (только выполненные операции)
    p = out_dir / f"Все_транзакции_{ts}.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Транзакции"
    ws.append(["ID", "Дата", "Счет-источник", "Счет-получатель", "Сумма", "Причина", "ID сделки", "Кто создал"])
    for t in await rows("SELECT * FROM transactions ORDER BY id DESC"):
        ws.append([int(t["id"]), str(t["date"]), str(t["account_from"] or ""), str(t["account_to"] or ""), float(t["amount"] or 0), str(t["reason"] or ""), str(t["deal_id"] or ""), str(t["created_by"] or "")])
    wb.save(p)
    files.append(p)

    # Выплаты (ожидается)
    p = out_dir / f"Выплаты_(ожидается)_{ts}.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ожидается"
    ws.append(["ID", "ID сделки", "Тип", "ID пользователя", "Инвестор", "Сумма", "Оплачено", "Дата оплаты"])
    for r in await rows("SELECT * FROM payouts WHERE is_paid=0 ORDER BY payout_id DESC"):
        ws.append([int(r["payout_id"]), int(r["deal_id"]), str(r["kind"]), str(r["user_id"] or ""), str(r["investor_id"] or ""), float(r["amount"] or 0), int(r["is_paid"] or 0), str(r["paid_at"] or "")])
    # Формат ID пользователя как текст (чтобы Excel не делал 1.92E+09)
    for row in ws.iter_rows(min_row=2, min_col=4, max_col=4):
        for cell in row:
            cell.number_format = "@"
    wb.save(p)
    files.append(p)

    # Выплаты (выполнено)
    p = out_dir / f"Выплаты_(выполнено)_{ts}.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Выполнено"
    ws.append(["ID", "ID сделки", "Тип", "ID пользователя", "Инвестор", "Сумма", "Оплачено", "Дата оплаты"])
    for r in await rows("SELECT * FROM payouts WHERE is_paid=1 ORDER BY payout_id DESC"):
        ws.append([int(r["payout_id"]), int(r["deal_id"]), str(r["kind"]), str(r["user_id"] or ""), str(r["investor_id"] or ""), float(r["amount"] or 0), int(r["is_paid"] or 0), str(r["paid_at"] or "")])
    for row in ws.iter_rows(min_row=2, min_col=4, max_col=4):
        for cell in row:
            cell.number_format = "@"
    wb.save(p)
    files.append(p)

    # Долги
    p = out_dir / f"Долги_{ts}.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Долги"
    ws.append(["ID долга", "Инвестор", "Сумма", "Процент %", "Срок", "Статус", "Создано"])
    for r in await rows("SELECT * FROM loans ORDER BY loan_id DESC"):
        ws.append([int(r["loan_id"]), str(r["investor_id"]), float(r["principal"] or 0), float(r["interest_percent"] or 0), str(r["due_date"]), str(r["status"]), str(r["created_at"] or "")])
    wb.save(p)
    files.append(p)

    # Счета
    p = out_dir / f"Счета_{ts}.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Счета"
    ws.append(["ID счета", "Название", "Баланс"])
    for r in await rows("SELECT * FROM accounts ORDER BY account_id"):
        ws.append([str(r["account_id"]), str(r["title"]), float(r["balance"] or 0)])
    wb.save(p)
    files.append(p)

    # Отчёты (сводка закрытия)
    p = out_dir / f"Отчёты_{ts}.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Сводка"
    ws.append(["ID сделки", "Прибыль", "% капитала", "Капитал", "Инвестор", "Пул исполнителей", "Бонус торга", "Всего выплат", "Создано"])
    for r in await rows("SELECT * FROM deal_close_summary ORDER BY deal_id DESC"):
        ws.append([int(r["deal_id"]), float(r["profit"] or 0), float(r["cap_rate"] or 0), float(r["cap_cut"] or 0), float(r["inv_cut"] or 0), float(r["performer_pool"] or 0), float(r["bargain_bonus"] or 0), float(r["payouts_total"] or 0), str(r["created_at"] or "")])
    wb.save(p)
    files.append(p)

    for f in files:
        await message.answer_document(FSInputFile(f))



@dp.message(F.text == "📋 Мои задачи")
async def my_tasks(message: Message):
    await ensure_user(DBH, CFG, message.from_user)
    tasks = await _db_rows(
        """
        SELECT * FROM general_tasks
        WHERE assignee_id=? AND status!='done'
        ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'mid' THEN 2 ELSE 3 END, due_date IS NULL, due_date
        """,
        (message.from_user.id,)
    )
    if not tasks:
        return await message.answer("✅ Нет активных задач.")
    lines = ["Ваши задачи:"]
    for t in tasks[:50]:
        pr = PRIORITY_ICON.get(t["priority"], "🟠")
        lines.append(f"{pr} #{t['id']} {t['title']}")
        if t["description"]:
            lines.append(f"   📝 {t['description']}")
        state_ru = {'open':'Активна','overdue':'Просрочено','done':'Выполнено'}.get(t["status"], t["status"])
        lines.append(f"   ⏰ Дедлайн: {t['due_date'] or '—'} ({state_ru})")
    await message.answer("\n".join(lines))


@dp.message(F.text == "➕ Создать задачу")
async def create_task_start(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    await state.clear()
    msg, mapping = await members_numbered(DBH)
    await state.update_data(member_map=mapping)
    await state.set_state(GenTaskCreate.assignee)
    await message.answer("Назначить кому?\n" + msg)


@dp.message(GenTaskCreate.assignee)
async def create_task_assignee(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    mapping = (await state.get_data())["member_map"]
    try:
        ids = parse_choice_ids(message.text, mapping)
    except Exception as e:
        return await message.answer(f"⛔ {e}")
    await state.update_data(assignee_id=ids[0])
    await state.set_state(GenTaskCreate.priority)
    await message.answer("Приоритет:\n1. низкий\n2. средний\n3. высокий")


@dp.message(GenTaskCreate.priority)
async def create_task_priority(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    m = {"1":"low","2":"mid","3":"high"}
    t = message.text.strip()
    if t not in m:
        return await message.answer("Введите 1..3.")
    await state.update_data(priority=m[t])
    await state.set_state(GenTaskCreate.title)
    await message.answer("Название задачи")


@dp.message(GenTaskCreate.title)
async def create_task_title(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    await state.update_data(title=message.text.strip())
    await state.set_state(GenTaskCreate.description)
    await message.answer("Описание (можно '-')")


@dp.message(GenTaskCreate.description)
async def create_task_desc(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    txt = message.text.strip()
    await state.update_data(description=None if txt == "-" else txt)
    await state.set_state(GenTaskCreate.due)
    await message.answer("⏰ Дедлайн\n1. сегодня\n\nИли: 09.12.2026\nИли '-' если без дедлайна")


@dp.message(GenTaskCreate.due)
async def create_task_due(message: Message, state: FSMContext):
    await ensure_user(DBH, CFG, message.from_user)
    txt = message.text.strip()
    if txt in ("2", "2."): 
        return await message.answer("⛔ Дедлайн 'вчера' запрещён.")
    due = None
    if txt != "-":
        try:
            due = parse_date(txt)
            if due < date.today().isoformat():
                return await message.answer("⛔ Дедлайн не может быть в прошлом.")
        except Exception:
            return await message.answer("⛔ Неверная дата или '-'.")
    data = await state.get_data()
    async with DBH.connect() as con:
        await con.execute(
            "INSERT INTO general_tasks(creator_id, assignee_id, priority, title, description, due_date, status) VALUES(?,?,?,?,?,?,?)",
            (message.from_user.id, int(data["assignee_id"]), data["priority"], data["title"], data.get("description"), due, "open"),
        )
        await con.commit()
    await state.clear()
    await message.answer("✅ Задача создана.")

async def main():
    global BOT, CFG, DBH
    settings = load_settings()
    CFG = load_config(settings.config_path)

    data_dir = Path(settings.data_dir)
    (data_dir / "files").mkdir(parents=True, exist_ok=True)
    (data_dir / "exports").mkdir(parents=True, exist_ok=True)
    (data_dir / "backups").mkdir(parents=True, exist_ok=True)

    DBH = DB(settings.db_path)
    await DBH.init("schema.sql")
    await DBH.ensure_base_accounts(CFG)

    BOT = Bot(token=settings.bot_token)
    print("Bot started")
    await dp.start_polling(BOT)


if __name__ == "__main__":
    asyncio.run(main())
