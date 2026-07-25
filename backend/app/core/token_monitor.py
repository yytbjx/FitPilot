"""Token 用量实时监控与自动熔断。

依据开发需求：实时累计 prompt/completion Token；
当用量超过「预算 × TOKEN_STOP_RATIO（默认 50%）」时自动停止后续 LLM 调用。
"""

from __future__ import annotations

import threading
import time
from contextvars import ContextVar
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


# ---------- 多租户分桶（迭代 2） ----------

# 当前调用链归属的用户；agent runner 在任务开始时 set，LLM 客户端读取。
# 用 contextvars 避免沿 graph → ollama_client 调用链显式改几十个签名。
_budget_user: ContextVar[int | None] = ContextVar("fitpilot_token_budget_user", default=None)


def set_token_budget_user(user_id: int | None):
    """设置当前上下文的 Token 预算归属用户，返回可 reset 的 token。"""
    return _budget_user.set(user_id)


def reset_token_budget_user(token: Any) -> None:
    """恢复上一个预算归属用户。"""
    _budget_user.reset(token)


def current_token_budget_user() -> int | None:
    """读取当前上下文的预算归属用户（未设置返回 None）。"""
    return _budget_user.get()


class TokenBudgetManager:
    """按 user_id 分桶的 Token 预算管理器 + 全局桶兜底熔断。

    - 每个用户独立 TokenMonitor（预算 = token_budget_per_user），单用户打满只熔断自己；
    - 全局桶（token_budget_global）作为整站成本兜底；
    - ensure_allowed / record 同时作用于全局桶与（若有）用户桶。
    """

    # 防御性上限：用户数异常膨胀时清空重建，避免内存泄漏
    _MAX_USER_BUCKETS = 10_000

    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or get_settings()
        self.stop_ratio = s.token_stop_ratio
        self.per_user_budget = s.token_budget_per_user
        self.global_monitor = TokenMonitor(
            budget=s.token_budget_global, stop_ratio=s.token_stop_ratio
        )
        self._users: dict[int, TokenMonitor] = {}
        self._lock = threading.Lock()

    def user_monitor(self, user_id: int) -> TokenMonitor:
        with self._lock:
            if len(self._users) >= self._MAX_USER_BUCKETS:
                logger.warning("token_budget_user_buckets_reset", size=len(self._users))
                self._users.clear()
            monitor = self._users.get(user_id)
            if monitor is None:
                monitor = TokenMonitor(budget=self.per_user_budget, stop_ratio=self.stop_ratio)
                self._users[user_id] = monitor
            return monitor

    def ensure_allowed(self, user_id: int | None = None) -> None:
        """LLM 调用前检查：全局桶或用户桶任一熔断即抛错。"""
        self.global_monitor.ensure_allowed()
        if user_id is not None:
            self.user_monitor(user_id).ensure_allowed()

    def record(
        self,
        user_id: int | None = None,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        source: str = "ollama",
    ) -> TokenUsageSnapshot:
        """累加一次调用的 Token（全局 + 用户桶），返回用户桶（或全局）快照。"""
        snap = self.global_monitor.record(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            source=source,
        )
        if user_id is not None:
            snap = self.user_monitor(user_id).record(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                source=source,
            )
        return snap

    def reset(self) -> None:
        """重置全部计数（仅管理/测试用途）。"""
        self.global_monitor.reset()
        with self._lock:
            self._users.clear()


_budget_manager: TokenBudgetManager | None = None
_budget_manager_lock = threading.Lock()


def get_budget_manager() -> TokenBudgetManager:
    """获取进程级 TokenBudgetManager 单例。"""
    global _budget_manager
    if _budget_manager is None:
        with _budget_manager_lock:
            if _budget_manager is None:
                _budget_manager = TokenBudgetManager()
    return _budget_manager
