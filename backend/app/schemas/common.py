"""统一 API 响应信封与健康检查相关 Schema。"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorBody(BaseModel):
    """错误体：code + message + 可选细节。"""

    code: str
    message: str
    details: dict[str, Any] | None = None


class ApiResponse(BaseModel, Generic[T]):
    """文档约定的统一 envelope。"""

    request_id: str
    status: str = Field(description="success | error")
    data: T | None = None
    error: ErrorBody | None = None


class TokenUsageOut(BaseModel):
    """Token 用量对外结构。"""

    used: int
    prompt_tokens: int
    completion_tokens: int
    budget: int
    stop_ratio: float
    stop_threshold: int
    usage_ratio: float
    usage_percent: float
    remaining_until_stop: int
    call_count: int
    stopped: bool


class ChatRequest(BaseModel):
    """简易对话请求（用于连通性与 Token 监控验证）。"""

    message: str = Field(min_length=1, max_length=4000)
    system: str | None = Field(
        default="你是 FitPilot 健身与膳食助手，只提供一般性健康建议，不做医学诊断。",
        description="系统提示词",
    )


class ChatResponse(BaseModel):
    """对话响应。"""

    reply: str
    model: str | None = None
    token_usage: dict[str, Any]
