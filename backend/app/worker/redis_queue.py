"""Redis 任务队列（LPUSH / BRPOP）。"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings

QUEUE_KEY = "fitpilot:agent:queue"


def _redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


async def enqueue_agent_task(payload: dict[str, Any]) -> str:
    """入队 Agent 任务，返回 task_id。"""
    task_id = str(payload.get("task_id") or "")
    client = _redis()
    try:
        await client.lpush(QUEUE_KEY, json.dumps(payload, ensure_ascii=False))
        return task_id
    finally:
        await client.aclose()


async def dequeue_agent_task(*, timeout: int = 5) -> dict[str, Any] | None:
    """阻塞出队一条任务。"""
    client = _redis()
    try:
        item = await client.brpop(QUEUE_KEY, timeout=timeout)
        if not item:
            return None
        _, raw = item
        return json.loads(raw)
    finally:
        await client.aclose()


async def queue_depth() -> int:
    client = _redis()
    try:
        return int(await client.llen(QUEUE_KEY))
    finally:
        await client.aclose()
