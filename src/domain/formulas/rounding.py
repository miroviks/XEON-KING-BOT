from __future__ import annotations

import math


def distribute_pool(raw_entries: list[float], pool: float) -> list[float]:
    total_cents = round(pool * 100)
    cents = [math.floor(v * 100) for v in raw_entries]
    rest = total_cents - sum(cents)
    ranking = sorted(range(len(cents)), key=lambda i: raw_entries[i], reverse=True)
    idx = 0
    while rest > 0 and ranking:
        cents[ranking[idx % len(ranking)]] += 1
        rest -= 1
        idx += 1
    return [c / 100 for c in cents]
