"""健康检查与依赖连通性探测（Postgres / Redis / Qdrant / Ollama / GPU）。"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Request
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.deps import get_request_id, ok
from app.core.config import get_settings
from app.core.token_monitor import get_token_monitor
from app.db.session import get_engine
from app.services.ollama_client import get_ollama_client
from app.services.qdrant_client import get_qdrant_service

router = APIRouter(tags=["health"])


def _gpu_info() -> dict[str, Any]:
    """探测 PyTorch CUDA 与显存，用于模型选型校验。"""
    try:
        import torch

        cuda_ok = torch.cuda.is_available()
        info: dict[str, Any] = {
            "torch_version": torch.__version__,
            "cuda_available": cuda_ok,
            "cuda_version": getattr(torch.version, "cuda", None),
        }
        if cuda_ok:
            props = torch.cuda.get_device_properties(0)
            total = props.total_memory
            info.update(
                {
                    "device_name": props.name,
                    "total_memory_gb": round(total / (1024**3), 2),
                    "recommended_llm": "qwen3.5:4b",
                    "recommended_embedding": "BAAI/bge-small-zh-v1.5",
                    "recommended_reranker": "BAAI/bge-reranker-base",
                }
            )
        return info
    except Exception as exc:  # noqa: BLE001 — 健康检查需吞掉探测异常
        return {"cuda_available": False, "error": str(exc)}


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """轻量健康检查：进程存活即返回。"""
    settings = get_settings()
    return ok(
        get_request_id(request),
        {
            "service": settings.app_name,
            "env": settings.app_env,
            "status": "up",
        },
    )


@router.get("/health/ready")
async def readiness(request: Request) -> dict[str, Any]:
    """就绪检查：逐项探测 PostgreSQL / Redis / Qdrant / Ollama。"""
    settings = get_settings()
    checks: dict[str, Any] = {}

    # PostgreSQL
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        checks["postgres"] = {"ok": False, "error": str(exc)}

    # Redis
    try:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        pong = await redis.ping()
        await redis.aclose()
        checks["redis"] = {"ok": bool(pong)}
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = {"ok": False, "error": str(exc)}

    # Qdrant（本机 Docker）
    try:
        checks["qdrant"] = get_qdrant_service().health()
    except Exception as exc:  # noqa: BLE001
        checks["qdrant"] = {"ok": False, "error": str(exc)}

    # Ollama（本机）
    try:
        checks["ollama"] = await get_ollama_client().health()
    except Exception as exc:  # noqa: BLE001
        checks["ollama"] = {"ok": False, "error": str(exc)}

    # GPU / PyTorch
    checks["gpu"] = _gpu_info()

    # Token 监控状态
    checks["token_monitor"] = get_token_monitor().snapshot().to_dict()

    overall = all(
        isinstance(v, dict) and v.get("ok") is True
        for k, v in checks.items()
        if k in {"postgres", "redis", "qdrant", "ollama"}
    )
    return ok(
        get_request_id(request),
        {"ready": overall, "checks": checks},
    )


@router.get("/metrics/tokens")
async def token_metrics(request: Request) -> dict[str, Any]:
    """实时 Token 用量查询（超过预算 50% 会 stopped=true）。"""
    return ok(get_request_id(request), get_token_monitor().snapshot().to_dict())
