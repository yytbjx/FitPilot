"""Token 用量实时监控与自动熔断。

依据开发需求：实时累计 prompt/completion Token；
当用量超过「预算 × TOKEN_STOP_RATIO（默认 50%）」时自动停止后续 LLM 调用。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class TokenBudgetExceeded(RuntimeError):
    """Token 用量超过停止阈值时抛出，调用方应中止 Agent / LLM 流程。"""

    def __init__(self, snapshot: "TokenUsageSnapshot") -> None:
        self.snapshot = snapshot
        super().__init__(
            f"Token 用量已达 {snapshot.usage_ratio:.1%} "
            f"（{snapshot.used}/{snapshot.budget}），超过停止阈值 "
            f"{snapshot.stop_ratio:.0%}（阈值 {snapshot.stop_threshold}），已自动停止。"
        )


@dataclass
class TokenUsageSnapshot:
    """某时刻的用量快照，便于 API / 日志展示。"""

    used: int
    prompt_tokens: int
    completion_tokens: int
    budget: int
    stop_ratio: float
    stop_threshold: int
    call_count: int
    stopped: bool
    updated_at: float

    @property
    def usage_ratio(self) -> float:
        """相对总预算的使用比例。"""
        if self.budget <= 0:
            return 1.0
        return self.used / self.budget

    @property
    def remaining_until_stop(self) -> int:
        """距离熔断阈值还剩多少 Token。"""
        return max(0, self.stop_threshold - self.used)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 API 友好结构。"""
        return {
            "used": self.used,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "budget": self.budget,
            "stop_ratio": self.stop_ratio,
            "stop_threshold": self.stop_threshold,
            "usage_ratio": round(self.usage_ratio, 4),
            "usage_percent": round(self.usage_ratio * 100, 2),
            "remaining_until_stop": self.remaining_until_stop,
            "call_count": self.call_count,
            "stopped": self.stopped,
            "updated_at": self.updated_at,
        }


@dataclass
class TokenMonitor:
    """线程安全的 Token 预算监视器（进程内单例）。"""

    budget: int
    stop_ratio: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    call_count: int = 0
    stopped: bool = False
    stop_reason: str | None = None
    updated_at: float = field(default_factory=time.time)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "TokenMonitor":
        """从配置创建监视器。"""
        s = settings or get_settings()
        return cls(budget=s.token_budget, stop_ratio=s.token_stop_ratio)

    @property
    def used(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def stop_threshold(self) -> int:
        return int(self.budget * self.stop_ratio)

    def snapshot(self) -> TokenUsageSnapshot:
        """生成当前快照。"""
        with self._lock:
            return TokenUsageSnapshot(
                used=self.used,
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
                budget=self.budget,
                stop_ratio=self.stop_ratio,
                stop_threshold=self.stop_threshold,
                call_count=self.call_count,
                stopped=self.stopped,
                updated_at=self.updated_at,
            )

    def ensure_allowed(self) -> None:
        """调用 LLM 前检查：已熔断或已达阈值则抛错。"""
        snap = self.snapshot()
        if snap.stopped or snap.used >= snap.stop_threshold:
            self.stopped = True
            self.stop_reason = self.stop_reason or "token_budget_ratio_exceeded"
            logger.warning(
                "token_budget_stop",
                **snap.to_dict(),
            )
            raise TokenBudgetExceeded(snap)

    def record(
        self,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        source: str = "ollama",
    ) -> TokenUsageSnapshot:
        """累加一次调用的 Token，并在超限时标记停止。"""
        with self._lock:
            self.prompt_tokens += max(0, int(prompt_tokens))
            self.completion_tokens += max(0, int(completion_tokens))
            self.call_count += 1
            self.updated_at = time.time()
            snap = self.snapshot()
            logger.info(
                "token_usage_updated",
                source=source,
                delta_prompt_tokens=prompt_tokens,
                delta_completion_tokens=completion_tokens,
                usage=snap.to_dict(),
            )
            if snap.used >= snap.stop_threshold and not self.stopped:
                self.stopped = True
                self.stop_reason = "token_budget_ratio_exceeded"
                logger.error(
                    "token_budget_auto_stop",
                    msg="Token 用量超过 50% 预算阈值，自动停止后续 LLM 调用",
                    usage=snap.to_dict(),
                )
            return self.snapshot()

    def reset(self) -> None:
        """重置计数（仅管理/测试用途）。"""
        with self._lock:
            self.prompt_tokens = 0
            self.completion_tokens = 0
            self.call_count = 0
            self.stopped = False
            self.stop_reason = None
            self.updated_at = time.time()


# 进程级单例：全链路共享同一份实时用量
_monitor: TokenMonitor | None = None
_monitor_lock = threading.Lock()


def get_token_monitor() -> TokenMonitor:
    """获取全局 Token 监视器。"""
    global _monitor
    if _monitor is None:
        with _monitor_lock:
            if _monitor is None:
                _monitor = TokenMonitor.from_settings()
    return _monitor
