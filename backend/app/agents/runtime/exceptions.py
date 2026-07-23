"""Agent Runtime 异常。"""

from __future__ import annotations


class AgentRuntimeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ToolExecutionError(AgentRuntimeError):
    def __init__(self, tool: str, message: str) -> None:
        super().__init__("TOOL_ERROR", f"{tool}: {message}")
        self.tool = tool


class ValidationFailed(AgentRuntimeError):
    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__("VALIDATION_FAILED", message)
        self.errors = errors or []


class ApprovalRequired(AgentRuntimeError):
    def __init__(self, message: str = "需要人工确认") -> None:
        super().__init__("APPROVAL_REQUIRED", message)
