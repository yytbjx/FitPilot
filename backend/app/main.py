"""FitPilot FastAPI 入口。

职责：
- 初始化日志与中间件（注入 request_id）
- 挂载 API 路由与 Prometheus 指标
- 启动时打印本机模型/显存选型摘要
"""

from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app import __version__
from app.api import api_router
from app.api.deps import fail
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.token_monitor import TokenBudgetExceeded, get_token_monitor

setup_logging()
logger = get_logger(__name__)
settings = get_settings()

# ---------- Prometheus 指标 ----------
REQUEST_COUNT = Counter(
    "fitpilot_http_requests_total",
    "HTTP 请求总数",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "fitpilot_http_request_duration_seconds",
    "HTTP 请求耗时（秒）",
    ["method", "path"],
)

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="个性化训练与膳食协同 AI Agent 系统后端",
)

def _cors_origins() -> list[str]:
    """生产环境禁止 credentials + 通配 * 组合；开发可用 *。"""
    raw = (settings.cors_origins or "*").strip()
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if settings.app_env == "production":
        if not origins or origins == ["*"]:
            # 未显式配置时回退到本机前端，避免开放任意源
            return ["http://127.0.0.1:5173", "http://localhost:5173"]
        return [o for o in origins if o != "*"]
    return origins or ["*"]


_origins = _cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")
# 兼容旧客户端（无版本前缀）
app.include_router(api_router)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """为每个请求注入 request_id，并记录延迟指标。"""
    request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:12]}"
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    path = request.url.path
    REQUEST_COUNT.labels(request.method, path, str(response.status_code)).inc()
    REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(TokenBudgetExceeded)
async def token_budget_handler(request: Request, exc: TokenBudgetExceeded):
    """全局捕获 Token 熔断异常。"""
    rid = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=429,
        content=fail(rid, "TOKEN_BUDGET_EXCEEDED", str(exc), details=exc.snapshot.to_dict()),
    )


@app.get("/metrics")
async def prometheus_metrics() -> Response:
    """Prometheus scrape 端点。"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


_WEAK_JWT = {
    "change-me",
    "change-me-fitpilot-dev-secret-please",
    "secret",
    "jwt-secret",
}


@app.on_event("startup")
async def on_startup() -> None:
    """启动摘要：配置、Token 阈值、推荐模型；生产校验 JWT/CORS。"""
    if settings.app_env == "production" and settings.jwt_secret.strip() in _WEAK_JWT:
        raise RuntimeError(
            "生产环境禁止使用弱 JWT_SECRET，请在 .env 中设置足够强度的随机密钥"
        )
    if settings.app_env == "production" and _origins == ["*"]:
        raise RuntimeError("生产环境禁止 CORS allow_origins=* ，请设置 CORS_ORIGINS")

    monitor = get_token_monitor()
    logger.info(
        "fitpilot_startup",
        version=__version__,
        env=settings.app_env,
        cors_origins=_origins,
        ollama_url=settings.ollama_base_url,
        ollama_model=settings.ollama_model,
        ollama_models_by_role=settings.ollama_model_roles(),
        ollama_keep_alive=settings.ollama_keep_alive,
        embedding_model=settings.resolved_embedding_model,
        embedding_device=settings.embedding_device,
        reranker_model=settings.resolved_reranker_model,
        reranker_device=settings.reranker_device,
        qdrant_url=settings.qdrant_url,
        agent_use_worker=settings.agent_use_worker,
        token_budget=monitor.budget,
        token_stop_ratio=monitor.stop_ratio,
        token_stop_threshold=monitor.stop_threshold,
    )


# uvicorn app.main:app --reload
