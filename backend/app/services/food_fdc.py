"""从 USDA Foundation Foods（优先中文翻译包）导入宏量到 Postgres。

数据优先级：
1) knowledge_base/raw/curated/fdc/foundation_foods_macros_zh.json
2) 例子或数据/...中文翻译包/食品基础信息_中英对照.csv
3) 英文原始 FoundationFoods JSON（回退）
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.food import FoodItem

SOURCE = "usda-foundation"

NUT_PROTEIN = {"203"}
NUT_FAT = {"204"}
NUT_CARB = {"205", "205.2"}
NUT_ENERGY_KCAL = {"208", "957", "958"}
NUT_ENERGY_KJ = {"268"}

ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = ROOT / "例子或数据"
ZH_PACK = EXAMPLES / "FoodData_Central_foundation_food_2026-04-30_中文翻译包"
KB_FDC = ROOT / "knowledge_base" / "raw" / "curated" / "fdc"


def default_macros_path() -> Path:
    candidates = [
        KB_FDC / "foundation_foods_macros_zh.json",
        ZH_PACK / "食品基础信息_中英对照.csv",
        EXAMPLES / "FoodData_Central_foundation_food_json_2026-04-30.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError("找不到 USDA 宏量数据（JSON/CSV），请先运行 scripts/prepare_fdc_kb.py")


def _amount(nutrients: list[dict[str, Any]], numbers: set[str]) -> float | None:
    for n in nutrients:
        nut = n.get("nutrient") or {}
        num = str(nut.get("number") or "")
        if num in numbers:
            amt = n.get("amount")
            if amt is None:
                continue
            try:
                return float(amt)
            except (TypeError, ValueError):
                continue
    return None


def _energy_kcal(nutrients: list[dict[str, Any]]) -> float:
    kcal = _amount(nutrients, NUT_ENERGY_KCAL)
    if kcal is not None:
        return kcal
    kj = _amount(nutrients, NUT_ENERGY_KJ)
    if kj is not None:
        return kj / 4.184
    return 0.0


def _f(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _row_from_macros(item: dict[str, Any]) -> dict[str, Any] | None:
    fdc_id = item.get("fdcId") or item.get("external_id")
    name_zh = (item.get("name_zh") or item.get("食品中文名") or "").strip()
    name_en = (item.get("name_en") or item.get("食品英文名") or "").strip()
    name = name_zh or name_en
    if not fdc_id or not name:
        return None
    category = (
        item.get("category_zh")
        or item.get("分类中文")
        or item.get("category_en")
        or item.get("分类英文")
        or "Foundation Foods"
    )
    return {
        "source": SOURCE,
        "external_id": str(fdc_id),
        "name": name[:256],
        "name_en": (name_en or None),
        "brand": "USDA Foundation",
        "category": str(category)[:64],
        "serving_g": 100.0,
        "kcal_per_100g": round(_f(item.get("kcal_per_100g") or item.get("能量_kcal_每100g")), 2),
        "protein_g_per_100g": round(
            _f(item.get("protein_g_per_100g") or item.get("蛋白质_g_每100g")), 2
        ),
        "carb_g_per_100g": round(
            _f(item.get("carb_g_per_100g") or item.get("碳水化合物_g_每100g")), 2
        ),
        "fat_g_per_100g": round(_f(item.get("fat_g_per_100g") or item.get("脂肪_g_每100g")), 2),
    }


def _load_from_macros_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items") if isinstance(data, dict) else data
    out = []
    for item in items or []:
        mapped = _row_from_macros(item)
        if mapped:
            out.append(mapped)
    return out


def _load_from_summary_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        field_map = {(k or "").replace("\ufeff", "").strip(): k for k in (reader.fieldnames or [])}

        def g(row: dict, *names: str) -> str:
            for n in names:
                key = field_map.get(n) or n
                if key in row and row[key] not in (None, ""):
                    return str(row[key]).strip()
            for n in names:
                for fk, orig in field_map.items():
                    if n in fk and row.get(orig) not in (None, ""):
                        return str(row[orig]).strip()
            return ""

        out: list[dict[str, Any]] = []
        for row in reader:
            mapped = _row_from_macros(
                {
                    "fdcId": g(row, "fdcId"),
                    "name_zh": g(row, "食品中文名"),
                    "name_en": g(row, "食品英文名"),
                    "category_zh": g(row, "分类中文"),
                    "category_en": g(row, "分类英文"),
                    "kcal_per_100g": g(row, "能量_kcal_每100g"),
                    "protein_g_per_100g": g(row, "蛋白质_g_每100g"),
                    "fat_g_per_100g": g(row, "脂肪_g_每100g"),
                    "carb_g_per_100g": g(row, "碳水化合物_g_每100g"),
                }
            )
            if mapped:
                out.append(mapped)
        return out


def map_foundation_food(raw: dict[str, Any]) -> dict[str, Any] | None:
    """英文原始 JSON 回退映射。"""
    if not isinstance(raw, dict):
        return None
    fdc_id = raw.get("fdcId")
    name_zh = str(raw.get("descriptionZh") or "").strip() or None
    name_en = str(raw.get("description") or "").strip()
    name = name_zh or name_en
    if not fdc_id or not name:
        return None
    nutrients = list(raw.get("foodNutrients") or [])
    cat = raw.get("foodCategory")
    category = None
    if isinstance(cat, dict):
        category = cat.get("descriptionZh") or cat.get("description") or cat.get("code")
    elif isinstance(cat, str):
        category = cat
    return {
        "source": SOURCE,
        "external_id": str(fdc_id),
        "name": name[:256],
        "name_en": name_en[:256] if name_en else None,
        "brand": "USDA Foundation",
        "category": (str(category)[:64] if category else "Foundation Foods"),
        "serving_g": 100.0,
        "kcal_per_100g": round(_energy_kcal(nutrients), 2),
        "protein_g_per_100g": round(_amount(nutrients, NUT_PROTEIN) or 0.0, 2),
        "carb_g_per_100g": round(_amount(nutrients, NUT_CARB) or 0.0, 2),
        "fat_g_per_100g": round(_amount(nutrients, NUT_FAT) or 0.0, 2),
    }


def load_foundation_foods(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or default_macros_path()
    if path.suffix.lower() == ".csv":
        return _load_from_summary_csv(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        return _load_from_macros_json(path)
    foods = data.get("FoundationFoods") if isinstance(data, dict) else data
    if not isinstance(foods, list):
        raise ValueError(f"无法解析 USDA 文件: {path}")
    out: list[dict[str, Any]] = []
    for item in foods:
        mapped = map_foundation_food(item) if isinstance(item, dict) else None
        if mapped:
            out.append(mapped)
    return out


async def upsert_foods(
    db: AsyncSession,
    rows: Iterable[dict[str, Any]],
    *,
    batch_size: int = 100,
) -> dict[str, int]:
    inserted = updated = 0
    batch: list[dict[str, Any]] = []

    async def flush(chunk: list[dict[str, Any]]) -> None:
        nonlocal inserted, updated
        ids = [r["external_id"] for r in chunk]
        existing = {
            e.external_id: e
            for e in (
                await db.scalars(
                    select(FoodItem).where(
                        FoodItem.source == SOURCE,
                        FoodItem.external_id.in_(ids),
                    )
                )
            ).all()
        }
        for row in chunk:
            cur = existing.get(row["external_id"])
            payload = dict(row)
            if cur is None:
                name_hit = await db.scalar(select(FoodItem).where(FoodItem.name == payload["name"]))
                if name_hit is not None and (
                    name_hit.source != SOURCE or name_hit.external_id != payload["external_id"]
                ):
                    payload["name"] = f"{payload['name'][:230]} [fdc:{payload['external_id']}]"
                db.add(FoodItem(**payload))
                inserted += 1
            else:
                for k, v in payload.items():
                    setattr(cur, k, v)
                updated += 1

    for row in rows:
        batch.append(row)
        if len(batch) >= batch_size:
            await flush(batch)
            await db.flush()
            batch = []
    if batch:
        await flush(batch)
        await db.flush()
    await db.commit()
    return {"inserted": inserted, "updated": updated, "total": inserted + updated}
