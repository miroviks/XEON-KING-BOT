from __future__ import annotations


def apply_task_weight(
    base_weight: float,
    complexity_multiplier: float,
    ai_multiplier: float,
    uses_complexity: bool,
    uses_ai: bool,
    task_type: str,
) -> float:
    weight = base_weight
    if uses_complexity or task_type in {"list", "sell", "repair", "execute"}:
        weight *= complexity_multiplier
    if uses_ai:
        weight *= ai_multiplier
    return weight


def task_share(performer_pool: float, weight: float, sum_weights: float, performers_count: int) -> float:
    if sum_weights <= 0 or performers_count <= 0:
        return 0.0
    return (performer_pool * weight / sum_weights) / performers_count
