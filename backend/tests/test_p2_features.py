"""检查点与食谱/评估扩展单测。"""

from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.eval.full_eval import run_full_eval
from app.eval.generation_eval import run_generation_eval
from app.eval.meal_eval import run_meal_eval
from app.eval.plan_eval import run_plan_eval
from app.eval.safety_eval import run_safety_eval
from app.graphs.checkpointer import PostgresCheckpointSaver
from app.services.meal_optimizer import optimize_meals


def test_checkpoint_next_version():
    saver = PostgresCheckpointSaver.__new__(PostgresCheckpointSaver)
    v1 = BaseCheckpointSaver.get_next_version(saver, None, None)
    v2 = BaseCheckpointSaver.get_next_version(saver, v1, None)
    assert v1 != v2


def test_ortools_meal_optimizer_macro_error():
    foods = [
        {"id": 1, "name": "鸡胸肉", "kcal_per_100g": 165, "protein_g_per_100g": 31, "carb_g_per_100g": 0, "fat_g_per_100g": 3.6},
        {"id": 2, "name": "燕麦", "kcal_per_100g": 389, "protein_g_per_100g": 17, "carb_g_per_100g": 66, "fat_g_per_100g": 7},
        {"id": 3, "name": "西兰花", "kcal_per_100g": 34, "protein_g_per_100g": 2.8, "carb_g_per_100g": 7, "fat_g_per_100g": 0.4},
        {"id": 4, "name": "糙米", "kcal_per_100g": 111, "protein_g_per_100g": 2.6, "carb_g_per_100g": 23, "fat_g_per_100g": 0.9},
        {"id": 5, "name": "鸡蛋", "kcal_per_100g": 155, "protein_g_per_100g": 13, "carb_g_per_100g": 1.1, "fat_g_per_100g": 11},
    ]
    targets = {"kcal": 2000, "protein_g": 120, "carb_g": 200, "fat_g": 60}
    meals = optimize_meals(foods, targets, use_ortools=True)
    assert len(meals) == 3
    total_kcal = sum(i.get("kcal_est", 0) for m in meals for i in m.get("items") or [])
    assert total_kcal > 0
    err = abs(total_kcal - 2000) / 2000
    assert err <= 0.25  # 允许求解器近似


def test_eval_layers_offline():
    root = Path(__file__).resolve().parents[2]
    assert run_plan_eval(root / "evals" / "plan_cases.json").ok
    gen = run_generation_eval(root / "evals" / "generation_cases.json")
    # 静态用例必须过；e2e 在无 Qdrant 时可 skip
    assert gen.total >= 3
    assert gen.ok, gen.summary_text()
    assert run_safety_eval(root / "evals" / "safety_cases.json").ok
    meal = run_meal_eval(root / "evals" / "meal_cases.json")
    assert meal.total >= 3
    assert meal.ok, meal.summary_text()


def test_meal_swap_locked():
    meals = optimize_meals(
        [
            {"id": 1, "name": "鸡胸肉", "kcal_per_100g": 165, "protein_g_per_100g": 31, "carb_g_per_100g": 0, "fat_g_per_100g": 3.6},
            {"id": 2, "name": "燕麦", "kcal_per_100g": 389, "protein_g_per_100g": 17, "carb_g_per_100g": 66, "fat_g_per_100g": 7},
            {"id": 3, "name": "西兰花", "kcal_per_100g": 34, "protein_g_per_100g": 2.8, "carb_g_per_100g": 7, "fat_g_per_100g": 0.4},
        ],
        {"kcal": 2000, "protein_g": 120, "carb_g": 200, "fat_g": 60},
        use_ortools=True,
    )
    from app.services.meal_optimizer import swap_meal_item

    foods = [
        {"id": 1, "name": "鸡胸肉", "kcal_per_100g": 165, "protein_g_per_100g": 31, "carb_g_per_100g": 0, "fat_g_per_100g": 3.6},
        {"id": 2, "name": "燕麦", "kcal_per_100g": 389, "protein_g_per_100g": 17, "carb_g_per_100g": 66, "fat_g_per_100g": 7},
        {"id": 4, "name": "鸡蛋", "kcal_per_100g": 155, "protein_g_per_100g": 13, "carb_g_per_100g": 1.1, "fat_g_per_100g": 11},
    ]
    swapped = swap_meal_item(
        meals,
        meal_index=0,
        foods=foods,
        daily_targets={"kcal": 2000, "protein_g": 120},
        use_ortools=True,
    )
    assert swapped["ok"] is True
    assert len(swapped["meals"]) == 3


def test_full_eval_config_smoke(tmp_path):
    """编排冒烟：只验证各层能跑通出报告（检索质量门禁在 eval-gate / eval 命令）。

    在线检索层逐条走 hybrid_retrieve（Qdrant 不可用时每条有连接开销），
    golden 集扩充到 51 条后全量会拖慢单测数倍；冒烟用 dataset_limit 截断。
    """
    import yaml

    from app.eval.rag_eval import load_eval_config

    root = Path(__file__).resolve().parents[2]
    cfg = load_eval_config(root / "evals" / "eval_config.yaml")
    cfg.setdefault("parameters", {})["dataset_limit"] = 5
    cfg_path = tmp_path / "eval_config_smoke.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    report = run_full_eval(config_path=cfg_path, repo_root=root, suite_set="small")
    assert len(report.layers) >= 5
    assert report.summary_text().startswith("=== FitPilot")
