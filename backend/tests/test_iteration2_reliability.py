"""迭代 2 后端可靠性单测（纯单测，不依赖 DB / 外部服务）。

覆盖：
(a) 取消后 finalize 不覆盖 cancelled；
(b) 注册密码策略；
(c) 事件 seq 唯一冲突重试；
(d) reaper 状态转移判定（纯函数）；
(e) 每用户并发任务上限；
(f) Token 预算多租户分桶隔离。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.application.agent.create_task import create_agent_task
from app.core.config import Settings
from app.core.token_monitor import TokenBudgetExceeded, TokenBudgetManager
from app.models.agent_task import AgentTask
from app.schemas.auth_biz import RegisterRequest
from app.services.agent_persistence import append_task_event, mark_task_finished
from app.services.agent_reaper import is_stale_queued, is_stale_running
from app.services.agent_task_finalize import finalize_agent_result


# ---------- DB fakes ----------


class _Nested:
    async def __aenter__(self) -> "_Nested":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class FakeSession:
    """最小 AsyncSession 替身：get/scalar/add/flush/commit/begin_nested/expunge。"""

    def __init__(self, *, row: Any = None, scalars: list[Any] | None = None) -> None:
        self.row = row
        self.scalars = list(scalars or [])
        self.added: list[Any] = []
        self.commits = 0
        self.fail_next_flush = False
        self.expunged: list[Any] = []

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self.row

    async def scalar(self, _stmt: Any) -> Any:
        return self.scalars.pop(0) if self.scalars else None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        if self.fail_next_flush:
            self.fail_next_flush = False
            # 模拟并发方抢先写入同 seq：唯一约束冲突
            raise IntegrityError("INSERT", {}, Exception("duplicate key (task_id, seq)"))

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass

    def begin_nested(self) -> _Nested:
        return _Nested()

    def expunge(self, obj: Any) -> None:
        self.expunged.append(obj)


def _task(status: str) -> AgentTask:
    t = AgentTask(id="task_x", user_id=1, message="m")
    t.status = status
    return t


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------- (a) 取消后 finalize 不覆盖 cancelled ----------


def test_mark_task_finished_keeps_cancelled() -> None:
    row = _task("cancelled")
    db = FakeSession(row=row)
    _run(mark_task_finished(db, "task_x", status="failed", error_code="AGENT_ERROR"))
    assert row.status == "cancelled"
    assert row.completed_at is None
    assert row.error_code is None


def test_mark_task_finished_allows_remark_cancelled() -> None:
    row = _task("cancelled")
    db = FakeSession(row=row)
    _run(mark_task_finished(db, "task_x", status="cancelled"))
    assert row.status == "cancelled"
    assert row.completed_at is not None


def test_finalize_short_circuits_cancelled_task() -> None:
    row = _task("cancelled")
    db = FakeSession(row=row)
    calls: list[tuple[str, dict]] = []

    async def _persist(session: Any, task_id: str, ev: dict) -> None:
        calls.append((task_id, ev))

    out = _run(
        finalize_agent_result(
            db,
            task_id="task_x",
            result={"final_status": "completed", "reply": "done", "events": []},
            persist_event=_persist,
        )
    )
    assert out == "cancelled"
    assert calls == []
    assert row.status == "cancelled"


# ---------- (b) 注册密码策略 ----------


def test_register_password_policy() -> None:
    ok = RegisterRequest(email="a@b.com", password="abcd1234xy")
    assert ok.password == "abcd1234xy"

    with pytest.raises(ValueError):
        RegisterRequest(email="a@b.com", password="abc123")  # 少于 10 位
    with pytest.raises(ValueError):
        RegisterRequest(email="a@b.com", password="abcdefghij")  # 无数字
    with pytest.raises(ValueError):
        RegisterRequest(email="a@b.com", password="1234567890")  # 无字母


# ---------- (c) 事件 seq 唯一冲突重试 ----------


def test_append_task_event_retries_on_seq_conflict() -> None:
    # 初始 max(seq)=5 → 首次尝试 seq=6 冲突；并发方写入后 max=6 → 重试 seq=7 成功
    db = FakeSession(scalars=[5, 6])
    db.fail_next_flush = True
    row = _run(append_task_event(db, task_id="task_x", event_type="progress", payload={"e": 1}))
    assert row.seq == 7
    assert len(db.added) == 2  # 首次冲突行 + 重试行
    assert len(db.expunged) == 1  # 冲突行被摘除


def test_append_task_event_no_conflict_fast_path() -> None:
    db = FakeSession(scalars=[3])
    row = _run(append_task_event(db, task_id="task_x", event_type="progress", payload={}))
    assert row.seq == 4
    assert len(db.added) == 1


# ---------- (d) reaper 状态转移判定 ----------


def test_reaper_queued_predicate() -> None:
    now = datetime.now(timezone.utc)
    old = now - timedelta(seconds=400)
    fresh = now - timedelta(seconds=100)
    assert is_stale_queued("queued", old, now=now, stale_seconds=300) is True
    assert is_stale_queued("queued", fresh, now=now, stale_seconds=300) is False
    assert is_stale_queued("running", old, now=now, stale_seconds=300) is False
    assert is_stale_queued("pending", old, now=now, stale_seconds=300) is False


def test_reaper_running_predicate() -> None:
    now = datetime.now(timezone.utc)
    started_long_ago = now - timedelta(seconds=2000)
    updated_recent = now - timedelta(seconds=10)
    assert (
        is_stale_running("running", started_long_ago, updated_recent, now=now, running_max_seconds=1800)
        is True
    )
    # started_at 缺失时回退 updated_at
    stale_updated = now - timedelta(seconds=2000)
    assert (
        is_stale_running("running", None, stale_updated, now=now, running_max_seconds=1800) is True
    )
    assert (
        is_stale_running("running", now, updated_recent, now=now, running_max_seconds=1800) is False
    )
    assert (
        is_stale_running("queued", started_long_ago, stale_updated, now=now, running_max_seconds=1800)
        is False
    )


# ---------- (e) 每用户并发任务上限 ----------


def test_create_task_concurrency_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    # 该用户已有 3 个 queued/pending/running 任务（默认上限 3）
    db = FakeSession(scalars=[3])
    out = _run(
        create_agent_task(
            db,
            user_id=1,
            message="帮我制定计划",
            session_id=None,
            trace_id="req_1",
        )
    )
    assert out["error"] == "CONCURRENCY_LIMIT"
    assert out["active"] == 3
    assert out["limit"] == 3


def test_create_task_under_limit_enqueues(monkeypatch: pytest.MonkeyPatch) -> None:
    enqueued: list[str] = []

    def _fake_enqueue(task_id: str, payload: dict, runner: Any) -> None:
        enqueued.append(task_id)

    monkeypatch.setattr("app.application.agent.create_task.enqueue_or_run", _fake_enqueue)
    # scalar 序列：并发计数=1 → 事件 max(seq)=0
    db = FakeSession(scalars=[1, 0])
    out = _run(
        create_agent_task(
            db,
            user_id=1,
            message="帮我制定计划",
            session_id=None,
            trace_id="req_1",
        )
    )
    assert out["deduped"] is False
    assert out["task_id"] in enqueued
    assert db.commits >= 2  # 任务行 + 起始事件各自提交


# ---------- (f) Token 预算多租户分桶 ----------


def test_token_budget_per_user_isolation() -> None:
    settings = Settings(token_budget_per_user=1000, token_budget_global=100_000, token_stop_ratio=0.5)
    mgr = TokenBudgetManager(settings)
    # 用户 A 打满自己的桶
    mgr.record(7, prompt_tokens=600, source="test")
    with pytest.raises(TokenBudgetExceeded):
        mgr.ensure_allowed(7)
    # 用户 B 不受影响
    mgr.ensure_allowed(8)
    # 匿名（无 user 上下文）仅受全局桶约束
    mgr.ensure_allowed(None)


def test_token_budget_global_fallback() -> None:
    settings = Settings(token_budget_per_user=100_000, token_budget_global=1000, token_stop_ratio=0.5)
    mgr = TokenBudgetManager(settings)
    # 多个用户各自远低于 per-user 预算，但合计打满全局桶
    mgr.record(1, prompt_tokens=300, source="test")
    mgr.record(2, prompt_tokens=300, source="test")
    with pytest.raises(TokenBudgetExceeded):
        mgr.ensure_allowed(3)
