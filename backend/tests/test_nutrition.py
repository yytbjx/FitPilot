"""营养确定性计算单测。"""

from app.services.nutrition import macros_from_per_100g, target_macros_for_goal, estimate_tdee


def test_macros_from_per_100g():
    m = macros_from_per_100g(200, 133, 26, 0, 2.3)
    assert m.kcal == 266.0
    assert m.protein_g == 52.0


def test_estimate_tdee_and_targets():
    e = estimate_tdee(sex="male", weight_kg=70, height_cm=175, age=28, activity_level="moderate")
    assert e["bmr"] > 1500
    assert e["tdee"] > e["bmr"]
    t = target_macros_for_goal(e["tdee"], "fat_loss", 70)
    assert t["kcal"] < e["tdee"]
    assert t["protein_g"] >= 100
