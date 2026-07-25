"""登录/注册限流（slowapi，内存滑动窗口）。

key = 客户端 IP + 端点路径，互不影响；进程内内存存储，
多实例部署时各实例独立计数（可接受的弱保证，见迭代报告）。
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.core.config import get_settings


def _ip_and_endpoint(request: Request) -> str:
    """限流维度：IP + endpoint，避免登录/注册互相挤占额度。"""
    return f"{get_remote_address(request)}:{request.url.path}"


limiter = Limiter(key_func=_ip_and_endpoint)


def auth_rate_limit() -> str:
    """从配置生成 slowapi 限流表达式（每次调用读取，便于测试改配置）。"""
    return f"{get_settings().auth_rate_limit_per_minute}/minute"
