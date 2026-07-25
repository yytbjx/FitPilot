"""Ollama 客户端封装：连接本机 Ollama，按环节选模型，并接入 Token 预算监控。"""

from __future__ import annotations

from typing import Any, Literal

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import LLM_GENERATION_COUNT, LLM_GENERATION_LATENCY, TOKEN_USAGE, timed_histogram
from app.core.token_monitor import (
    TokenBudgetExceeded,
    current_token_budget_user,
    get_budget_manager,
)
from app.core.tracing import add_step, finish_step

logger = get_logger(__name__)

ModelRole = Literal["default", "rag", "judge", "rewrite", "classify"]


class OllamaClient:
    """对 Ollama HTTP API 的薄封装（chat + 分角色模型 + keep_alive）。"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.ollama_base_url.rstrip("/")
        self.model = self.settings.ollama_model
        self.timeout = self.settings.ollama_timeout_seconds

    def model_for(self, role: ModelRole | str = "default") -> str:
        """按环节取模型名。"""
        return self.settings.resolve_ollama_model(str(role))

    async def health(self) -> dict[str, Any]:
        """检查 Ollama 是否可达及各角色模型是否已拉取。"""
        roles = self.settings.ollama_model_roles()
        async with httpx.AsyncClient(timeout=10.0) as client:
            tags = await client.get(f"{self.base_url}/api/tags")
            tags.raise_for_status()
            data = tags.json()
            names = [m.get("name") for m in data.get("models", [])]

            def _ready(model: str) -> bool:
                if model in names:
                    return True
                prefix = model.split(":")[0]
                return any(str(n).startswith(prefix) for n in names)

            role_ready = {k: _ready(v) for k, v in roles.items()}
            return {
                "ok": True,
                "base_url": self.base_url,
                "default_model": roles["default"],
                "models_by_role": roles,
                "role_ready": role_ready,
                "model_ready": all(role_ready.values()),
                "keep_alive": self.settings.ollama_keep_alive,
                "models": names,
            }

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        role: ModelRole | str | None = None,
        stream: bool = False,
        keep_alive: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """调用 /api/chat；可通过 role 或 model 指定模型；keep_alive 控制显存驻留。"""
        # 多租户分桶：优先熔断当前用户（contextvars 传入），全局桶兜底
        manager = get_budget_manager()
        budget_user = current_token_budget_user()
        manager.ensure_allowed(budget_user)
        if model:
            model_name = model
        elif role:
            model_name = self.model_for(role)
        else:
            model_name = self.model
        alive = keep_alive if keep_alive is not None else self.settings.ollama_keep_alive
        step = add_step("ollama.chat", "Ollama 生成", detail=f"{model_name} role={role or '-'}")
        LLM_GENERATION_COUNT.labels(model=model_name).inc()

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": stream,
            "keep_alive": alive,
        }
        if options:
            payload["options"] = options

        with timed_histogram(LLM_GENERATION_LATENCY, model=model_name):
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()

        prompt_tokens = int(data.get("prompt_eval_count") or 0)
        completion_tokens = int(data.get("eval_count") or 0)
        TOKEN_USAGE.labels(model=model_name, type="prompt").inc(prompt_tokens)
        TOKEN_USAGE.labels(model=model_name, type="completion").inc(completion_tokens)
        snap = manager.record(
            budget_user,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            source="ollama.chat",
        )
        if snap.stopped:
            logger.warning("ollama_chat_completed_but_budget_stopped", usage=snap.to_dict())
        finish_step(
            step,
            detail=f"prompt={prompt_tokens} completion={completion_tokens}",
        )

        return {
            "message": data.get("message", {}),
            "model": data.get("model") or model_name,
            "done": data.get("done", True),
            "token_usage": snap.to_dict(),
            "raw_counts": {
                "prompt_eval_count": prompt_tokens,
                "eval_count": completion_tokens,
            },
        }


# 便于依赖注入复用
_client: OllamaClient | None = None


def get_ollama_client() -> OllamaClient:
    global _client
    if _client is None:
        _client = OllamaClient()
    return _client


__all__ = ["OllamaClient", "get_ollama_client", "TokenBudgetExceeded", "ModelRole"]
