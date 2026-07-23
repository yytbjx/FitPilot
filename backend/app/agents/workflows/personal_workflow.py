"""个人数据与打卡引导工作流。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.progress import emit_progress
from app.graphs.state import FitnessAgentState
from app.tools.domain import get_user_profile_data, recent_logs


async def run_personal_workflow(state: FitnessAgentState, *, db: AsyncSession) -> dict[str, Any]:
    from app.agents.memory import confirmed_preferences, load_session_memory

    emit_progress(
        stage="personal",
        title="读取个人档案与近期记录",
        tool="get_user_profile_data",
    )
    profile = await get_user_profile_data(db, state["user_id"])
    prefs = await confirmed_preferences(db, user_id=state["user_id"])
    if prefs:
        # 已确认长期记忆覆盖档案缺省字段（不覆盖档案已有值）
        for k, v in prefs.items():
            raw = v.get("value") if isinstance(v, dict) and "value" in v else v
            if not profile.get(k) and raw is not None:
                profile[k] = raw
    logs = await recent_logs(db, state["user_id"])
    session_mem = None
    if state.get("session_id"):
        session_mem = await load_session_memory(
            db, user_id=state["user_id"], session_id=str(state["session_id"])
        )
    targets = (profile.get("nutrition_estimate") or {}).get("targets") or {}
    reply = (
        f"档案目标：{profile.get('goal') or '未设置'}；体重 {profile.get('weight_kg') or '-'} kg。\n"
        f"近 7 天训练次数 {logs['workout_count']}，饮食热量合计 {logs['diet_kcal']} kcal，"
        f"蛋白 {logs['diet_protein_g']} g。\n"
        f"规则估算目标：{targets or '请完善身高体重年龄后查看'}。"
    )
    if prefs:
        reply += f"\n已确认偏好键：{', '.join(prefs.keys())}。"
    if session_mem and session_mem.get("summary"):
        reply += f"\n会话摘要：{session_mem['summary']}"
    emit_progress(stage="personal", title="个人数据汇总完成", status="done", tool="recent_logs")
    return {
        "user_profile": profile,
        "workout_summary": logs.get("volume") or {},
        "diet_summary": {"kcal": logs["diet_kcal"], "protein_g": logs["diet_protein_g"]},
        "body_trend": {"items": logs.get("body_metrics") or []},
        "reply": reply,
        "final_status": "completed",
        "events": [{"event": "completed", "status": "personal_data", "confirmed_prefs": list(prefs.keys())}],
        "tool_results": [
            {"tool": "get_user_profile_data", "result": profile},
            {"tool": "recent_logs", "result": logs},
            {"tool": "confirmed_preferences", "result": prefs},
        ],
    }


async def run_logging_workflow(state: FitnessAgentState) -> dict[str, Any]:
    emit_progress(stage="log_hint", title="引导去记录页", detail="不在对话中直接写库", status="done")
    return {
        "reply": "请在「今日记录」页面录入训练/饮食（数值由食物库确定性计算）。此处仅引导，不直接写库。",
        "final_status": "completed",
        "events": [{"event": "completed", "status": "log_hint"}],
    }
