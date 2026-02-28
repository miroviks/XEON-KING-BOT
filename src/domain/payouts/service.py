from __future__ import annotations

from collections import defaultdict


def group_payouts(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[f"{row['kind']}:{row['recipient']}"] .append(row)
    return dict(grouped)
