"""食谱优化：OR-Tools 约束求解 + 贪心回退。"""



from __future__ import annotations



import logging

from typing import Any



logger = logging.getLogger(__name__)



MEAL_SLOTS = ["早餐", "午餐", "晚餐"]

MIN_GRAM = 30

MAX_GRAM = 350

GRAM_STEP = 10





def _score_greedy(food: dict[str, Any], targets: dict[str, float], meal_slot: str) -> float:

    kcal = float(food.get("kcal_per_100g") or 0)

    protein = float(food.get("protein_g_per_100g") or 0)

    target_kcal = float(targets.get("kcal") or 2000) / 3

    target_protein = float(targets.get("protein_g") or 120) / 3

    est_kcal = kcal * 3

    est_protein = protein * 3

    kcal_err = abs(est_kcal - target_kcal) / max(target_kcal, 1)

    protein_bonus = est_protein / max(target_protein, 1)

    slot_bonus = 0.1 if meal_slot == "早餐" and "燕麦" in str(food.get("name", "")) else 0

    return protein_bonus - kcal_err + slot_bonus





def _banned_foods(profile: dict[str, Any] | None) -> set[str]:

    if not profile:

        return set()

    raw = f"{profile.get('restrictions') or ''},{profile.get('diet_prefs') or ''}"

    return {x.strip().lower() for x in raw.split(",") if x.strip()}





def _optimize_greedy(

    foods: list[dict[str, Any]],

    targets: dict[str, Any],

    *,

    meal_names: list[str] | None = None,

) -> list[dict[str, Any]]:

    slots = meal_names or MEAL_SLOTS

    ranked = sorted(foods, key=lambda f: _score_greedy(f, targets, ""), reverse=True)

    meals: list[dict[str, Any]] = []

    used: set[int] = set()



    for slot in slots:

        picks: list[dict[str, Any]] = []

        for food in ranked:

            fid = food.get("id")

            if fid in used:

                continue

            if _score_greedy(food, targets, slot) > 0.3:

                amount = 100 if slot == "早餐" else 150

                picks.append(

                    {

                        "food_id": fid,

                        "name": food.get("name"),

                        "amount_g": amount,

                        "kcal_est": round(float(food.get("kcal_per_100g") or 0) * amount / 100, 1),

                        "protein_est": round(

                            float(food.get("protein_g_per_100g") or 0) * amount / 100, 1

                        ),

                    }

                )

                if fid is not None:

                    used.add(int(fid))

            if len(picks) >= 2:

                break

        idea = " + ".join(p["name"] for p in picks) if picks else "均衡搭配"

        meals.append({"name": slot, "idea": idea, "items": picks, "optimizer": "greedy"})

    return meals





def _optimize_ortools(

    foods: list[dict[str, Any]],

    targets: dict[str, Any],

    *,

    profile: dict[str, Any] | None = None,

    meal_names: list[str] | None = None,

) -> list[dict[str, Any]] | None:

    from ortools.linear_solver import pywraplp



    slots = meal_names or MEAL_SLOTS

    banned = _banned_foods(profile)

    eligible: list[dict[str, Any]] = []

    for f in foods:

        name = str(f.get("name") or "").lower()

        if any(b and b in name for b in banned):

            continue

        eligible.append(f)

    if not eligible:

        eligible = list(foods)

    if not eligible:

        return None



    solver = pywraplp.Solver.CreateSolver("SCIP")

    if not solver:

        return None



    n_foods = len(eligible)

    n_slots = len(slots)

    x: dict[tuple[int, int], Any] = {}

    y: dict[tuple[int, int], Any] = {}



    for i in range(n_foods):

        for j in range(n_slots):

            y[i, j] = solver.BoolVar(f"y_{i}_{j}")

            x[i, j] = solver.IntVar(0, MAX_GRAM // GRAM_STEP, f"x_{i}_{j}")

            solver.Add(x[i, j] <= (MAX_GRAM // GRAM_STEP) * y[i, j])



    for i in range(n_foods):

        solver.Add(solver.Sum(y[i, j] for j in range(n_slots)) <= 1)



    for j in range(n_slots):

        solver.Add(solver.Sum(y[i, j] for i in range(n_foods)) >= 1)

        solver.Add(solver.Sum(y[i, j] for i in range(n_foods)) <= 3)



    def _macro_sum(field: str) -> Any:

        return solver.Sum(

            x[i, j] * GRAM_STEP * float(eligible[i].get(field) or 0) / 100.0

            for i in range(n_foods)

            for j in range(n_slots)

        )



    total_kcal = _macro_sum("kcal_per_100g")

    total_protein = _macro_sum("protein_g_per_100g")

    total_carb = _macro_sum("carb_g_per_100g")

    total_fat = _macro_sum("fat_g_per_100g")



    target_kcal = float(targets.get("kcal") or 2000)

    target_protein = float(targets.get("protein_g") or 120)

    target_carb = float(targets.get("carb_g") or 200)

    target_fat = float(targets.get("fat_g") or 60)



    kcal_pos = solver.NumVar(0, solver.infinity(), "kcal_pos")

    kcal_neg = solver.NumVar(0, solver.infinity(), "kcal_neg")

    protein_pos = solver.NumVar(0, solver.infinity(), "protein_pos")

    protein_neg = solver.NumVar(0, solver.infinity(), "protein_neg")

    carb_pos = solver.NumVar(0, solver.infinity(), "carb_pos")

    carb_neg = solver.NumVar(0, solver.infinity(), "carb_neg")

    fat_pos = solver.NumVar(0, solver.infinity(), "fat_pos")

    fat_neg = solver.NumVar(0, solver.infinity(), "fat_neg")



    solver.Add(total_kcal - target_kcal == kcal_pos - kcal_neg)

    solver.Add(total_protein - target_protein == protein_pos - protein_neg)

    solver.Add(total_carb - target_carb == carb_pos - carb_neg)

    solver.Add(total_fat - target_fat == fat_pos - fat_neg)



    solver.Minimize(

        kcal_pos + kcal_neg

        + 1.5 * (protein_pos + protein_neg)

        + 0.5 * (carb_pos + carb_neg)

        + 0.5 * (fat_pos + fat_neg)

    )



    status = solver.Solve()

    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):

        return None



    meals: list[dict[str, Any]] = []

    for j, slot in enumerate(slots):

        picks: list[dict[str, Any]] = []

        for i in range(n_foods):

            if y[i, j].solution_value() < 0.5:

                continue

            grams = int(round(x[i, j].solution_value())) * GRAM_STEP

            if grams < MIN_GRAM:

                continue

            food = eligible[i]

            picks.append(

                {

                    "food_id": food.get("id"),

                    "name": food.get("name"),

                    "amount_g": grams,

                    "kcal_est": round(float(food.get("kcal_per_100g") or 0) * grams / 100, 1),

                    "protein_est": round(float(food.get("protein_g_per_100g") or 0) * grams / 100, 1),

                }

            )

        idea = " + ".join(p["name"] for p in picks) if picks else "均衡搭配"

        meals.append({"name": slot, "idea": idea, "items": picks, "optimizer": "ortools"})



    if not any(m["items"] for m in meals):

        return None

    return meals





def optimize_meals(

    foods: list[dict[str, Any]],

    targets: dict[str, Any],

    *,

    meal_names: list[str] | None = None,

    profile: dict[str, Any] | None = None,

    use_ortools: bool = True,

) -> list[dict[str, Any]]:

    """在宏量目标下优化三餐食物与克数；优先 OR-Tools，失败回退贪心。"""

    if not foods or not targets:

        return [

            {"name": "早餐", "idea": "燕麦+鸡蛋+牛奶", "items": [], "optimizer": "fallback"},

            {"name": "午餐", "idea": "鸡胸肉+米饭+西兰花", "items": [], "optimizer": "fallback"},

            {"name": "晚餐", "idea": "鱼肉+红薯+蔬菜", "items": [], "optimizer": "fallback"},

        ]



    if use_ortools:

        try:

            ortools_meals = _optimize_ortools(

                foods, targets, profile=profile, meal_names=meal_names

            )

            if ortools_meals:

                return ortools_meals

        except Exception as exc:  # noqa: BLE001

            logger.warning("ortools_meal_optimizer_failed: %s", exc)



    return _optimize_greedy(foods, targets, meal_names=meal_names)





def meal_macro_totals(meals: list[dict[str, Any]]) -> dict[str, float]:

    """汇总餐次宏量（用于评估）。"""

    kcal = protein = carb = fat = 0.0

    for meal in meals:

        for item in meal.get("items") or []:

            # items may not have carb/fat - estimate from food if missing

            kcal += float(item.get("kcal_est") or 0)

            protein += float(item.get("protein_est") or 0)

    return {"kcal": round(kcal, 1), "protein_g": round(protein, 1), "carb_g": carb, "fat_g": fat}


def swap_meal_item(
    meals: list[dict[str, Any]],
    *,
    meal_index: int,
    foods: list[dict[str, Any]],
    daily_targets: dict[str, Any],
    profile: dict[str, Any] | None = None,
    swap_food_id: int | None = None,
    use_ortools: bool = True,
) -> dict[str, Any]:
    """单餐换菜：锁定其他餐次，重优化指定餐次。"""
    if not meals or meal_index < 0 or meal_index >= len(meals):
        return {"ok": False, "error": "INVALID_MEAL_INDEX", "meals": meals}

    locked_ids: set[int] = set()
    for i, meal in enumerate(meals):
        if i == meal_index:
            continue
        for item in meal.get("items") or []:
            fid = item.get("food_id")
            if fid is not None:
                locked_ids.add(int(fid))

    pool = [f for f in foods if int(f.get("id") or -1) not in locked_ids]
    if swap_food_id is not None:
        forced = next((f for f in pool if int(f.get("id") or -1) == int(swap_food_id)), None)
        if forced:
            pool = [forced] + [f for f in pool if int(f.get("id") or -1) != int(swap_food_id)]

    slot_name = str(meals[meal_index].get("name") or MEAL_SLOTS[meal_index % 3])
    other_macros = meal_macro_totals([m for j, m in enumerate(meals) if j != meal_index])
    remain_targets = {
        "kcal": max(float(daily_targets.get("kcal") or 2000) - other_macros["kcal"], 200),
        "protein_g": max(float(daily_targets.get("protein_g") or 120) - other_macros["protein_g"], 20),
        "carb_g": max(float(daily_targets.get("carb_g") or 200) - other_macros.get("carb_g", 0), 20),
        "fat_g": max(float(daily_targets.get("fat_g") or 60) - other_macros.get("fat_g", 0), 10),
    }

    new_slot = optimize_meals(
        pool,
        remain_targets,
        profile=profile,
        meal_names=[slot_name],
        use_ortools=use_ortools,
    )
    out = [dict(m) for m in meals]
    out[meal_index] = new_slot[0] if new_slot else meals[meal_index]
    totals = meal_macro_totals(out)
    return {
        "ok": True,
        "meals": out,
        "meal_index": meal_index,
        "slot": slot_name,
        "daily_totals": totals,
        "optimizer": out[meal_index].get("optimizer"),
    }

