"""Agent 统一执行结果。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


from app.agents.runtime.policies import build_approval_payload


class AgentStepResult(BaseModel):
    step_id: str
    tool: str
    status: Literal["ok", "error", "skipped"] = "ok"
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    retry_count: int = 0


class AgentRunResult(BaseModel):
    ok: bool = True
    status: str = "completed"
    reply: str = ""
    citations: list[dict[str, Any]] = Field(default_factory=list)
    pending_actions: dict[str, Any] | None = None
    steps: list[AgentStepResult] = Field(default_factory=list)
    requires_approval: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_state_update(self) -> dict[str, Any]:
        evs: list[dict[str, Any]] = []
        if self.requires_approval and self.pending_actions:
            pending = self.pending_actions
            approval = build_approval_payload(
                pending,
                log_basis=self.metadata.get("log_basis"),
                knowledge_citations=self.citations or None,
                risk_notes=self.metadata.get("risk_notes"),
            )
            evs.append({"event": "approval_required", **approval})
        else:
            evs.append({"event": "completed", "status": self.status})
        return {
            "reply": self.reply,
            "citations": self.citations,
            "final_status": self.status,
            "pending_actions": self.pending_actions,
            "requires_confirmation": self.requires_approval,
            "events": evs,
            "tool_results": [
                {"tool": s.tool, "result": s.output_summary, "status": s.status} for s in self.steps
            ],
        }
