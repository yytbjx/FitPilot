"""任务进度实时推送：供 Agent / RAG 在执行中写入 SSE 事件缓冲。"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Callable

ProgressSink = Callable[[dict[str, Any]], None]

_sink: ContextVar[ProgressSink | None] = ContextVar("fitpilot_progress_sink", default=None)


def set_progress_sink(sink: ProgressSink | None):
    """绑定当前任务的进度回调，返回 token 供 reset。"""
    return _sink.set(sink)


def reset_progress_sink(token) -> None:
    _sink.reset(token)


def emit_progress(
    *,
    stage: str,
    title: str,
    detail: str | None = None,
    tool: str | None = None,
    status: str = "running",
    extra: dict[str, Any] | None = None,
) -> None:
    """推送一条进度事件（若当前上下文无 sink 则静默忽略）。"""
    sink = _sink.get()
    if sink is None:
        return
    payload: dict[str, Any] = {
        "event": "progress",
        "stage": stage,
        "title": title,
        "detail": detail,
        "tool": tool,
        "status": status,
    }
    if extra:
        payload["extra"] = extra
    sink(payload)
