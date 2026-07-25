"""受控记忆 / 审批载荷 / 快照服务单测（不依赖外部服务）。"""

from __future__ import annotations

from app.agents.memory.session_memory import summarize_session
from app.agents.memory.user_memory import ALLOWED_KEYS
from app.agents.workflows.approval import build_approval_payload, requires_approval
from app.application.memories.confirm_memory import (
    PROFILE_FIELD_MAP,
    _serialize_profile_value,
    _unwrap_value,
)


def test_summarize_session():
    s = summarize_session(
        {"goal": "减脂", "intents": ["plan_adjust"], "pending": True},
        reply="已生成预览",
    )
    assert "减脂" in s
    assert "待确认" in s


def test_allowed_memory_keys():
    assert "goal" in ALLOWED_KEYS
    assert "diet_prefs" in ALLOWED_KEYS
    assert "random_chat" not in ALLOWED_KEYS


def test_profile_writeback_helpers():
    assert PROFILE_FIELD_MAP["goal"] == "goal"
    assert _unwrap_value({"value": "fat_loss"}) == "fat_loss"
    assert _unwrap_value("fat_loss") == "fat_loss"
    assert _serialize_profile_value("weekly_sessions", "4") == 4
    assert _serialize_profile_value("equipment", ["哑铃", "杠铃"]) == "哑铃,杠铃"


def test_approval_payload_fields():
    assert requires_approval("commit_plan") is True
    assert requires_approval("query_knowledge") is False
    pending = {
        "workout_plan_id": 1,
        "diet_plan_id": 2,
        "preview": {"workout": {"title": "W"}, "diet": {"title": "D"}},
        "diff": {"workout": ["- a", "+ b"]},
        "weekly_reason": "完成率偏低",
        "validation": {"ok": True},
    }
    payload = build_approval_payload(
        pending,
        log_basis={"workout_count": 3, "days": 14},
        knowledge_citations=[{"index": 1, "title": "恢复"}],
    )
    assert payload["type"] == "plan_approval"
    assert payload["can_rollback"] is True
    assert payload["data_basis"]["logs"]["workout_count"] == 3
    assert payload["diff"]["workout"]
    assert payload["risk_notes"]
    assert payload["operation"]


def test_qdrant_service_has_snapshot_api():
    from app.services.qdrant_client import QdrantService

    assert hasattr(QdrantService, "create_snapshot")
    assert hasattr(QdrantService, "list_snapshots")
    assert hasattr(QdrantService, "recover_snapshot")
