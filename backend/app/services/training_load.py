"""训练负荷确定性汇总。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass


@dataclass
class SetVolume:
    """单次动作容量。"""

    exercise: str
    sets: int
    reps: int
    weight_kg: float

    @property
    def volume(self) -> float:
        return float(self.sets * self.reps * self.weight_kg)


def weekly_volume(entries: list[SetVolume]) -> dict:
    """按动作汇总周容量。"""
    by_ex: dict[str, float] = defaultdict(float)
    total = 0.0
    for e in entries:
        v = e.volume
        by_ex[e.exercise] += v
        total += v
    return {
        "total_volume": round(total, 1),
        "by_exercise": {k: round(v, 1) for k, v in by_ex.items()},
        "entries": [asdict(e) | {"volume": round(e.volume, 1)} for e in entries],
    }
