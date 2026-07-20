"""Token 监控单元测试。"""

import pytest

from app.core.token_monitor import TokenBudgetExceeded, TokenMonitor


def test_token_monitor_stops_at_half_budget() -> None:
    """用量达到预算 50% 时应熔断。"""
    mon = TokenMonitor(budget=1000, stop_ratio=0.5)
    mon.record(prompt_tokens=300, completion_tokens=100)
    assert mon.used == 400
    assert not mon.stopped

    mon.record(prompt_tokens=100, completion_tokens=0)
    assert mon.used == 500
    assert mon.stopped

    with pytest.raises(TokenBudgetExceeded):
        mon.ensure_allowed()


def test_token_monitor_snapshot_fields() -> None:
    """快照字段完整。"""
    mon = TokenMonitor(budget=10_000, stop_ratio=0.5)
    snap = mon.record(prompt_tokens=10, completion_tokens=5)
    assert snap.budget == 10_000
    assert snap.stop_threshold == 5_000
    assert snap.to_dict()["usage_percent"] >= 0
    assert "used" in snap.to_dict()
