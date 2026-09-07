"""评测设备加速规划单测（不依赖真实 GPU）。"""

from app.core.config import get_settings
from app.eval import device_accel as da


def test_plan_cpu_forced(monkeypatch):
    monkeypatch.setattr(da, "cuda_probe", lambda: (True, 5000, 6144))
    plan = da.plan_eval_devices("cpu")
    assert plan.embedding_device == "cpu"
    assert plan.reranker_device == "cpu"


def test_plan_cuda_forced_when_unavailable(monkeypatch):
    monkeypatch.setattr(da, "cuda_probe", lambda: (False, None, None))
    plan = da.plan_eval_devices("cuda")
    assert plan.embedding_device == "cpu"
    assert plan.reranker_device == "cpu"
    assert "回退" in plan.reason


def test_plan_auto_both_when_vram_enough(monkeypatch):
    monkeypatch.setattr(da, "cuda_probe", lambda: (True, 4500, 6144))
    plan = da.plan_eval_devices("auto")
    assert plan.embedding_device == "cuda"
    assert plan.reranker_device == "cuda"


def test_plan_auto_embed_only_when_vram_limited(monkeypatch):
    monkeypatch.setattr(da, "cuda_probe", lambda: (True, 1500, 6144))
    plan = da.plan_eval_devices("auto")
    assert plan.embedding_device == "cuda"
    assert plan.reranker_device == "cpu"


def test_plan_auto_cpu_when_vram_tight(monkeypatch):
    monkeypatch.setattr(da, "cuda_probe", lambda: (True, 400, 6144))
    plan = da.plan_eval_devices("auto")
    assert plan.embedding_device == "cpu"
    assert plan.reranker_device == "cpu"


def test_apply_mutates_settings_only(monkeypatch):
    monkeypatch.setattr(da, "cuda_probe", lambda: (True, 4500, 6144))
    settings = get_settings()
    prev_emb = settings.embedding_device
    prev_rr = settings.reranker_device
    try:
        plan = da.apply_eval_device_accel("auto")
        assert plan.embedding_device == "cuda"
        assert settings.embedding_device == "cuda"
        assert settings.reranker_device == "cuda"
    finally:
        # 恢复，避免污染同进程其它测试
        settings.embedding_device = prev_emb
        settings.reranker_device = prev_rr
        da._reset_model_singletons()
