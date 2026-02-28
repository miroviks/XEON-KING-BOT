from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Transaction:
    account_from: str | None
    account_to: str | None
    amount: float
    reason: str
    deal_id: int | None
    created_by: int | None


class DB:
    """Extracted DB-layer contract from monolith app.py."""

    def create_transaction(self, tx: Transaction) -> None:
        raise NotImplementedError

    def get_account_balance(self, account_id: str) -> float:
        raise NotImplementedError

    def create_deal(self, payload: dict) -> int:
        raise NotImplementedError

    def get_deal(self, deal_id: int) -> dict:
        raise NotImplementedError

    def close_deal(self, deal_id: int, status: str) -> None:
        raise NotImplementedError
