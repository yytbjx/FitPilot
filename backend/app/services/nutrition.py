"""营养确定性计算：禁止由 LLM 直接编造宏量/热量。"""

from __future__ import annotations

from dataclasses import asdict, dataclass


ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "athlete": 1.9,
}


@dataclass
class MacroTotals:
    """宏量合计。"""

    amount_g: float = 0.0
    kcal: float = 0.0
    protein_g: float = 0.0
    carb_g: float = 0.0
    fat_g: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def macros_from_per_100g(
    amount_g: float,
    kcal_per_100g: float,
    protein_g_per_100g: float,
    carb_g_per_100g: float,
    fat_g_per_100g: float,
) -> MacroTotals:
    """按重量从每 100g 营养成分换算。"""
    ratio = amount_g / 100.0
    return MacroTotals(
        amount_g=amount_g,
        kcal=round(kcal_per_100g * ratio, 2),
        protein_g=round(protein_g_per_100g * ratio, 2),
        carb_g=round(carb_g_per_100g * ratio, 2),
        fat_g=round(fat_g_per_100g * ratio, 2),
    )


def sum_macros(items: list[MacroTotals]) -> MacroTotals:
    """累加多条宏量。"""
    total = MacroTotals()
    for item in items:
        total.amount_g += item.amount_g
        total.kcal += item.kcal
        total.protein_g += item.protein_g
        total.carb_g += item.carb_g
        total.fat_g += item.fat_g
    total.kcal = round(total.kcal, 2)
    total.protein_g = round(total.protein_g, 2)
    total.carb_g = round(total.carb_g, 2)
    total.fat_g = round(total.fat_g, 2)
    return total


def mifflin_bmr(*, sex: str | None, weight_kg: float, height_cm: float, age: int) -> float:
    """Mifflin-St Jeor BMR。"""
    s = (sex or "").lower()
    if s in {"female", "f", "女"}:
        return 10 * weight_kg + 6.25 * height_cm - 5 * age - 161
    # 默认按男性公式
    return 10 * weight_kg + 6.25 * height_cm - 5 * age + 5


def estimate_tdee(
    *,
    sex: str | None,
    weight_kg: float,
    height_cm: float,
    age: int,
    activity_level: str | None = "moderate",
) -> dict[str, float]:
    """估算 BMR / TDEE。"""
    bmr = mifflin_bmr(sex=sex, weight_kg=weight_kg, height_cm=height_cm, age=age)
    factor = ACTIVITY_FACTORS.get((activity_level or "moderate").lower(), 1.55)
    tdee = bmr * factor
    return {"bmr": round(bmr, 1), "tdee": round(tdee, 1), "activity_factor": factor}


def target_macros_for_goal(tdee: float, goal: str | None, weight_kg: float) -> dict[str, float]:
    """按目标给出热量与宏量建议（规则，非 LLM）。"""
    g = (goal or "maintain").lower()
    if g in {"fat_loss", "cut", "减脂"}:
        kcal = tdee * 0.8
    elif g in {"muscle_gain", "bulk", "增肌"}:
        kcal = tdee * 1.1
    else:
        kcal = tdee
    protein = max(1.6 * weight_kg, 0.0)
    fat = max(0.8 * weight_kg, 0.0)
    protein_kcal = protein * 4
    fat_kcal = fat * 9
    carb_kcal = max(kcal - protein_kcal - fat_kcal, 0.0)
    carb = carb_kcal / 4
    return {
        "kcal": round(kcal, 1),
        "protein_g": round(protein, 1),
        "carb_g": round(carb, 1),
        "fat_g": round(fat, 1),
    }
