from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class BotSettings:
    bot_token: str
    admin_ids: set[int]


def _parse_admin_ids(raw: str) -> set[int]:
    values = set()
    for chunk in raw.split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        values.add(int(chunk))
    return values


def load_settings() -> BotSettings:
    token = os.getenv('BOT_TOKEN', '').strip()
    if not token:
        raise RuntimeError('BOT_TOKEN is empty. Set BOT_TOKEN in environment or .env')
    admin_ids = _parse_admin_ids(os.getenv('ADMIN_IDS', ''))
    return BotSettings(bot_token=token, admin_ids=admin_ids)
