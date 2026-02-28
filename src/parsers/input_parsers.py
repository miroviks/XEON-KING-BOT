from __future__ import annotations

import re
from datetime import date, timedelta


def parse_money(s: str) -> float:
    return float(s.replace(" ", "").replace(",", ".").strip())


def parse_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_date(s: str) -> str:
    value = s.strip().lower()
    if value in {"1", "1.", "сегодня", "today"}:
        return date.today().isoformat()
    if value in {"2", "2.", "вчера", "yesterday"}:
        return (date.today() - timedelta(days=1)).isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    match = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", value)
    if match:
        dd, mm, yy = match.groups()
        return f"{yy}-{mm}-{dd}"
    raise ValueError("bad date format")
