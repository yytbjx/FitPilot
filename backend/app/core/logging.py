"""结构化日志配置（stdout 输出，满足文档「容器内不写临时文件」要求）。"""

import logging
import sys

import structlog

from app.core.config import get_settings


def setup_logging() -> None:
    """初始化 structlog + 标准 logging 桥接。"""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    structlog.configure(
        processors=[
            # 合并上下文变量（request_id / trace_id 等）
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # 开发环境可读，生产可改为 JSONRenderer
            structlog.dev.ConsoleRenderer()
            if settings.app_env == "development"
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None):
    """获取带模块名的 bound logger。"""
    return structlog.get_logger(name)
