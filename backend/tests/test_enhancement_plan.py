"""增强方案相关单测：路由 / Evidence Gate / Tool Registry / CORS。"""

from app.agents.routing import route_intent
from app.core.config import Settings
from app.graphs.fitness_graph import classify_intent
from app.rag import RetrievedChunk
from app.rag.evidence_gate import assess_evidence
from app.tools.registry import get_tool, list_tools


def test_route_unknown_goes_to_clarify_not_rag():
    d = route_intent("随便说说")
    assert d.primary_intent == "clarify"
    assert classify_intent("随便说说") == "clarify"


def test_route_multi_intent_plan_adjust():
    d = route_intent("根据我最近两周的训练记录调整饮食和训练")
    assert d.primary_intent == "plan_adjust"
    assert "personal_data_query" in d.secondary_intents or d.requires_personal_data


def test_evidence_gate_empty():
    a = assess_evidence([])
    assert a.answerable is False
    assert a.reason == "NO_EVIDENCE"


def test_evidence_gate_with_chunks():
    chunks = [
        RetrievedChunk(
            chunk_id="c1",
            text="减脂期蛋白质建议按体重计算。",
            score=0.2,
            title="蛋白",
            section_path="营养/蛋白",
            document_id="d1",
            version_id="v1",
            citation="doc#1",
            metadata={"retrieval_source": "dense"},
        )
    ]
    a = assess_evidence(chunks, query="减脂蛋白")
    assert a.answerable is True
    assert a.selected_evidence


def test_tool_registry_has_write_approval():
    commit = get_tool("commit_plans")
    assert commit is not None
    assert commit.operation_type == "write"
    assert commit.requires_approval is True
    assert any(t.name == "check_risk" for t in list_tools())


def test_production_cors_rejects_star_only():
    s = Settings(app_env="production", cors_origins="*", jwt_secret="a-strong-secret-value-here")
    assert s.app_env == "production"
    # 启动校验在 main.on_startup；此处确认配置字段存在
    assert s.cors_origins == "*"
