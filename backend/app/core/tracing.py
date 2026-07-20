"""本地步骤追踪（迁移自 llm-knowledge-base 的轻量 Trace 思路）。"""

from __future__ import annotations

import time
import uuid
from collections import deque
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from threading import Lock
from typing import Any


@dataclass
class TraceStep:
    name: str
    title: str
    status: str = "running"
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    detail: str | None = None
    error: str | None = None

    @property
    def duration_ms(self) -> float | None:
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at) * 1000


@dataclass
class Trace:
    id: str
    kind: str
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    steps: list[TraceStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": None
            if self.ended_at is None
            else (self.ended_at - self.started_at) * 1000,
            "meta": self.meta,
            "steps": [
                {
                    **asdict(s),
                    "duration_ms": s.duration_ms,
                }
                for s in self.steps
            ],
        }


_current: ContextVar[Trace | None] = ContextVar("fitpilot_trace", default=None)
_STORE: deque[Trace] = deque(maxlen=200)
_LOCK = Lock()


def start_trace(kind: str, **meta: Any) -> Trace:
    tr = Trace(id=f"tr_{uuid.uuid4().hex[:12]}", kind=kind, meta=dict(meta))
    _current.set(tr)
    with _LOCK:
        _STORE.appendleft(tr)
    return tr


def get_current_trace() -> Trace | None:
    return _current.get()


def end_trace() -> None:
    tr = _current.get()
    if tr:
        tr.ended_at = time.time()
    _current.set(None)


def add_step(name: str, title: str, *, detail: str | None = None) -> TraceStep | None:
    tr = _current.get()
    if tr is None:
        return None
    step = TraceStep(name=name, title=title, detail=detail)
    tr.steps.append(step)
    return step


def finish_step(
    step: TraceStep | None,
    *,
    status: str = "ok",
    detail: str | None = None,
    error: str | None = None,
) -> None:
    if step is None:
        return
    step.status = status
    step.ended_at = time.time()
    if detail is not None:
        step.detail = detail
    if error:
        step.error = error
        step.status = "error"


def list_traces(limit: int = 20) -> list[dict[str, Any]]:
    with _LOCK:
        items = list(_STORE)[: max(1, min(limit, 100))]
    return [t.to_dict() for t in items]


def get_trace(trace_id: str) -> dict[str, Any] | None:
    with _LOCK:
        for t in _STORE:
            if t.id == trace_id:
                return t.to_dict()
    return None
