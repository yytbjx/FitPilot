"""第二轮增强：PEV / RetrievalPlan / 工作流委派。"""

from app.agents.runtime.planner import build_execution_plan
from app.agents.runtime.validator import validate_plan_execution
from app.agents.runtime.result import AgentStepResult
from app.rag.retrieval_plan import build_retrieval_plan


def test_execution_plan_for_complex_adjust():
    plan = build_execution_plan("根据我最近两周的训练记录调整饮食和训练")
    assert plan.requires_approval is True
    tools = [s.tool for s in plan.steps]
    assert "get_user_profile_data" in tools
    assert "recent_logs" in tools or "weekly_adjust_preview" in tools or "preview_and_stage_plans" in tools


def test_execution_plan_knowledge():
    plan = build_execution_plan("减脂期蛋白质怎么安排")
    assert any(s.tool == "hybrid_retrieve" for s in plan.steps)


def test_validator_blocks_write_tool_success():
    from app.agents.runtime.planner import ExecutionPlan, PlanStep

    plan = ExecutionPlan(
        goal="x",
        steps=[PlanStep(step_id="s1", tool="commit_plans")],
        requires_approval=True,
    )
    steps = [
        AgentStepResult(step_id="s1", tool="commit_plans", status="ok", output_summary={}),
    ]
    report = validate_plan_execution(plan, steps, pending=None)
    assert report.ok is False


def test_retrieval_plan_strategies():
    simple = build_retrieval_plan("什么是蛋白质")
    assert simple.strategy in {"simple_fact", "default", "complex_explain"}
    risky = build_retrieval_plan("胸痛还能训练吗")
    assert risky.strategy == "high_risk"
    assert risky.authority_threshold == 2
    complex_q = build_retrieval_plan("为什么减脂期要同时控制热量并且保证蛋白质摄入")
    assert complex_q.strategy == "complex_explain"
