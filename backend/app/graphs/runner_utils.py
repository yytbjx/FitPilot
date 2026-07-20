"""Agent 图执行结果归一化（interrupt / 终态）。"""

from __future__ import annotations

from typing import Any


def normalize_graph_result(result: dict[str, Any], snapshot: Any | None) -> dict[str, Any]:
    """根据 LangGraph StateSnapshot 标注 interrupt 与终态。"""
    out = dict(result)
    if snapshot is None:
        out.setdefault("interrupted", False)
        return out

    interrupts = getattr(snapshot, "interrupts", ()) or ()
    has_next = bool(getattr(snapshot, "next", ()))
    if interrupts or has_next:
        out["interrupted"] = True
        out["final_status"] = "awaiting_confirmation"
        out["requires_confirmation"] = True
        payloads = []
        for item in interrupts:
            val = getattr(item, "value", item)
            if isinstance(val, dict):
                payloads.append(val)
            else:
                payloads.append({"value": val})
        if payloads:
            out["interrupt_payloads"] = payloads
            pending = out.get("pending_actions") or {}
            if not pending and payloads[0].get("preview"):
                out["pending_actions"] = {
                    "workout_plan_id": payloads[0].get("workout_plan_id"),
                    "diet_plan_id": payloads[0].get("diet_plan_id"),
                    "preview": payloads[0].get("preview"),
                    "diff": payloads[0].get("diff"),
                }
    else:
        out["interrupted"] = False
        out.setdefault("final_status", out.get("final_status") or "completed")
    return out


def approval_events_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    """从图结果提取需持久化/SSE 的事件。"""
    events: list[dict[str, Any]] = list(result.get("events") or [])
    if result.get("interrupted"):
        pending = result.get("pending_actions") or {}
        payloads = result.get("interrupt_payloads") or []
        payload = payloads[0] if payloads else {}
        ev = {
            "event": "approval_required",
            "plan_id": pending.get("workout_plan_id") or payload.get("workout_plan_id"),
            "workout_plan_id": pending.get("workout_plan_id") or payload.get("workout_plan_id"),
            "diet_plan_id": pending.get("diet_plan_id") or payload.get("diet_plan_id"),
            "preview": pending.get("preview") or payload.get("preview"),
            "diff": pending.get("diff") or payload.get("diff"),
            "task_id": result.get("task_id"),
            "interrupted": True,
        }
        if not any(e.get("event") == "approval_required" for e in events):
            events.append(ev)
    return events
