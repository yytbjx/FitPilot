"""从 exercises-dataset 导入动作库（仅文本；媒体受 Gym Visual 版权，默认不入库）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise

# 常见英文名 → 中文简称，用于计划展示与检索友好性
NAME_ZH_ALIASES: dict[str, str] = {
    "barbell bench press": "杠铃卧推",
    "barbell full squat": "杠铃深蹲",
    "barbell deadlift": "杠铃硬拉",
    "pull-up": "引体向上",
    "push-up": "俯卧撑",
    "dumbbell curl": "哑铃弯举",
    "plank": "平板支撑",
    "burpee": "波比跳",
    "cable seated row": "坐姿划船",
    "dumbbell lateral raise": "哑铃侧平举",
    "romanian deadlift": "罗马尼亚硬拉",
    "leg press": "腿举",
    "lat pulldown": "高位下拉",
    "overhead press": "推举",
}


def default_dataset_path() -> Path:
    """优先用「例子或数据」目录，其次兼容 _refs。"""
    candidates = [
        Path(r"D:/FitPilot/例子或数据/exercises-dataset-main/data/exercises.json"),
        Path(__file__).resolve().parents[3] / "例子或数据" / "exercises-dataset-main" / "data" / "exercises.json",
        Path(__file__).resolve().parents[3] / "_refs" / "exercises-dataset" / "exercises-dataset-main" / "data" / "exercises.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError("找不到 exercises.json，请确认已放到 例子或数据/exercises-dataset-main/data/")


def _display_zh(name_en: str, instructions_zh: str | None) -> str | None:
    alias = NAME_ZH_ALIASES.get(name_en.lower().strip())
    if alias:
        return alias
    # 没有别名时不强行从长说明里猜名称
    return None


def map_record(raw: dict[str, Any]) -> dict[str, Any]:
    name_en = str(raw.get("name") or "").strip()
    instructions = raw.get("instructions") or {}
    steps = raw.get("instruction_steps") or {}
    zh_text = (instructions.get("zh") or "").strip() or None
    en_text = (instructions.get("en") or "").strip() or None
    attribution = (raw.get("attribution") or "").strip()
    return {
        "source": "exercises-dataset",
        "external_id": str(raw.get("id") or "").strip(),
        "name_en": name_en,
        "name_zh": _display_zh(name_en, zh_text),
        "body_part": raw.get("body_part") or raw.get("category"),
        "equipment": raw.get("equipment"),
        "primary_muscle": raw.get("target"),
        "muscle_group": raw.get("muscle_group"),
        "secondary_muscles": list(raw.get("secondary_muscles") or []),
        "instructions_zh": zh_text,
        "instructions_en": en_text,
        "steps_zh": list(steps.get("zh") or []),
        "steps_en": list(steps.get("en") or []),
        "media_note": (
            "媒体版权归 Gym Visual；FitPilot 默认仅入库文本。"
            + (f" {attribution}" if attribution else "")
        )[:512],
        "tags": [
            t
            for t in [
                raw.get("body_part"),
                raw.get("equipment"),
                raw.get("target"),
                raw.get("category"),
            ]
            if t
        ],
    }


def load_dataset(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or default_dataset_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("exercises.json 应为数组")
    return [map_record(item) for item in data if item.get("id") and item.get("name")]


async def upsert_exercises(
    db: AsyncSession,
    rows: Iterable[dict[str, Any]],
    *,
    batch_size: int = 200,
) -> dict[str, int]:
    inserted = 0
    updated = 0
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            i, u = await _flush_batch(db, batch)
            inserted += i
            updated += u
            batch = []
    if batch:
        i, u = await _flush_batch(db, batch)
        inserted += i
        updated += u
    await db.commit()
    return {"inserted": inserted, "updated": updated, "total": inserted + updated}


async def _flush_batch(db: AsyncSession, batch: list[dict[str, Any]]) -> tuple[int, int]:
    inserted = 0
    updated = 0
    ids = [r["external_id"] for r in batch]
    existing = {
        e.external_id: e
        for e in (
            await db.scalars(select(Exercise).where(Exercise.external_id.in_(ids)))
        ).all()
    }
    for row in batch:
        cur = existing.get(row["external_id"])
        if cur is None:
            db.add(Exercise(**row))
            inserted += 1
        else:
            for k, v in row.items():
                setattr(cur, k, v)
            updated += 1
    await db.flush()
    return inserted, updated


def exercise_to_rag_text(ex: Exercise | dict[str, Any]) -> str:
    if isinstance(ex, Exercise):
        name_zh = ex.name_zh
        name_en = ex.name_en
        body_part = ex.body_part
        equipment = ex.equipment
        primary = ex.primary_muscle
        secondary = ex.secondary_muscles or []
        steps = ex.steps_zh or []
        instructions = ex.instructions_zh or ex.instructions_en or ""
        external_id = ex.external_id
    else:
        name_zh = ex.get("name_zh")
        name_en = ex.get("name_en")
        body_part = ex.get("body_part")
        equipment = ex.get("equipment")
        primary = ex.get("primary_muscle")
        secondary = ex.get("secondary_muscles") or []
        steps = ex.get("steps_zh") or []
        instructions = ex.get("instructions_zh") or ex.get("instructions_en") or ""
        external_id = ex.get("external_id")

    title = f"{name_zh or name_en} ({name_en})" if name_zh else str(name_en)
    lines = [
        f"动作: {title}",
        f"外部编号: {external_id}",
        f"部位: {body_part} | 器械: {equipment} | 目标肌群: {primary}",
        f"协同肌群: {', '.join(secondary) if secondary else '无'}",
        "步骤:",
    ]
    if steps:
        lines.extend(f"{i}. {s}" for i, s in enumerate(steps, 1))
    elif instructions:
        lines.append(str(instructions))
    return "\n".join(lines)
