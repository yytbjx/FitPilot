"""Redis Streams 任务队列：ACK / 重试 / 死信 / 深度监控。

流键：
- fitpilot:agent:tasks       主任务流
- fitpilot:agent:dead_letter 死信流

消费组：fitpilot-workers
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

STREAM_KEY = "fitpilot:agent:tasks"
DLQ_KEY = "fitpilot:agent:dead_letter"
GROUP_NAME = "fitpilot-workers"
# 兼容旧 LPUSH 队列（升级过渡期可排空）
LEGACY_QUEUE_KEY = "fitpilot:agent:queue"


def _redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


async def ensure_consumer_group(*, start_id: str = "0") -> None:
    """创建消费组（已存在则忽略）。"""
    client = _redis()
    try:
        try:
            await client.xgroup_create(STREAM_KEY, GROUP_NAME, id=start_id, mkstream=True)
        except Exception as exc:  # noqa: BLE001
            if "BUSYGROUP" not in str(exc):
                raise
    finally:
        await client.aclose()


async def enqueue_agent_task(payload: dict[str, Any]) -> str:
    """入队 Agent 任务，返回 task_id。"""
    task_id = str(payload.get("task_id") or "")
    body = {
        **payload,
        "attempt": int(payload.get("attempt") or 0),
        "enqueued_at": time.time(),
    }
    client = _redis()
    try:
        await ensure_consumer_group()
        await client.xadd(STREAM_KEY, {"payload": json.dumps(body, ensure_ascii=False)})
        return task_id
    finally:
        await client.aclose()


async def dequeue_agent_task(
    *,
    consumer: str,
    timeout: int = 5,
    max_retries: int | None = None,
) -> dict[str, Any] | None:
    """从消费组读取一条任务。

    返回字段额外包含：
    - _stream_id: Redis 消息 ID（用于 ACK）
    - attempt: 当前重试次数
    """
    settings = get_settings()
    retries = max_retries if max_retries is not None else settings.agent_queue_max_retries
    client = _redis()
    try:
        await ensure_consumer_group()
        # 先认领超时未 ACK 的 pending（崩溃恢复）
        claimed = await _auto_claim(client, consumer=consumer, min_idle_ms=settings.agent_queue_claim_idle_ms)
        if claimed:
            return claimed

        result = await client.xreadgroup(
            GROUP_NAME,
            consumer,
            streams={STREAM_KEY: ">"},
            count=1,
            block=max(timeout, 1) * 1000,
        )
        if not result:
            return None
        _stream, messages = result[0]
        if not messages:
            return None
        msg_id, fields = messages[0]
        return _parse_message(msg_id, fields, retries=retries)
    finally:
        await client.aclose()


async def _auto_claim(
    client: Redis,
    *,
    consumer: str,
    min_idle_ms: int,
) -> dict[str, Any] | None:
    """认领长时间未 ACK 的 pending 消息。"""
    try:
        res = await client.xautoclaim(
            STREAM_KEY,
            GROUP_NAME,
            consumer,
            min_idle_time=min_idle_ms,
            start_id="0-0",
            count=1,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("xautoclaim_unavailable: %s", exc)
        return None
    messages = []
    if isinstance(res, (list, tuple)) and len(res) >= 2:
        messages = res[1] or []
    if not messages:
        return None
    msg_id, fields = messages[0]
    settings = get_settings()
    return _parse_message(msg_id, fields, retries=settings.agent_queue_max_retries)


def _parse_message(
    msg_id: str,
    fields: dict[str, Any],
    *,
    retries: int,
) -> dict[str, Any] | None:
    raw = fields.get("payload") or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"raw": raw}
    payload["_stream_id"] = msg_id
    attempt = int(payload.get("attempt") or 0)
    payload["attempt"] = attempt
    if attempt > retries:
        payload["_dead_letter"] = True
    return payload


async def ack_agent_task(stream_id: str) -> None:
    """确认消息已成功处理。"""
    if not stream_id:
        return
    client = _redis()
    try:
        await client.xack(STREAM_KEY, GROUP_NAME, stream_id)
        await client.xdel(STREAM_KEY, stream_id)
    finally:
        await client.aclose()


async def fail_agent_task(
    payload: dict[str, Any],
    *,
    error: str,
    max_retries: int | None = None,
) -> str:
    """处理失败：未超限则重新入队（attempt+1），否则写入死信并 ACK 原消息。"""
    settings = get_settings()
    retries = max_retries if max_retries is not None else settings.agent_queue_max_retries
    stream_id = str(payload.get("_stream_id") or "")
    attempt = int(payload.get("attempt") or 0)
    clean = {k: v for k, v in payload.items() if not str(k).startswith("_")}
    client = _redis()
    try:
        if attempt >= retries:
            dead = {
                **clean,
                "attempt": attempt,
                "error": error,
                "failed_at": time.time(),
            }
            await client.xadd(DLQ_KEY, {"payload": json.dumps(dead, ensure_ascii=False)})
            if stream_id:
                await client.xack(STREAM_KEY, GROUP_NAME, stream_id)
                await client.xdel(STREAM_KEY, stream_id)
            return "dead_letter"

        # 指数退避后重新入队
        delay = min(2**attempt, 60)
        await asyncio_sleep(delay)
        clean["attempt"] = attempt + 1
        clean["last_error"] = error
        await client.xadd(STREAM_KEY, {"payload": json.dumps(clean, ensure_ascii=False)})
        if stream_id:
            await client.xack(STREAM_KEY, GROUP_NAME, stream_id)
            await client.xdel(STREAM_KEY, stream_id)
        return "retrying"
    finally:
        await client.aclose()


async def asyncio_sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


async def queue_depth() -> int:
    """主任务流长度。"""
    client = _redis()
    try:
        return int(await client.xlen(STREAM_KEY))
    finally:
        await client.aclose()


async def dead_letter_depth() -> int:
    client = _redis()
    try:
        return int(await client.xlen(DLQ_KEY))
    finally:
        await client.aclose()


async def pending_count() -> int:
    """消费组 pending 数量。"""
    client = _redis()
    try:
        await ensure_consumer_group()
        info = await client.xpending(STREAM_KEY, GROUP_NAME)
        if isinstance(info, dict):
            return int(info.get("pending") or 0)
        if isinstance(info, (list, tuple)) and info:
            return int(info[0] or 0)
        return 0
    except Exception:  # noqa: BLE001
        return 0
    finally:
        await client.aclose()
