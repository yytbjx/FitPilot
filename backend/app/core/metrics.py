"""领域 Prometheus 指标（迁移自 llm-knowledge-base 的 metrics 模式）。"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Generator

from prometheus_client import Counter, Histogram

RETRIEVAL_COUNT = Counter(
    "fitpilot_retrieval_total",
    "RAG 检索次数",
    ["stage"],
)
RETRIEVAL_LATENCY = Histogram(
    "fitpilot_retrieval_duration_seconds",
    "RAG 检索耗时",
    ["stage"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 15.0, 30.0],
)

LLM_GENERATION_COUNT = Counter(
    "fitpilot_llm_generation_total",
    "LLM 生成次数",
    ["model"],
)
LLM_GENERATION_LATENCY = Histogram(
    "fitpilot_llm_generation_duration_seconds",
    "LLM 生成耗时",
    ["model"],
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)

TOKEN_USAGE = Counter(
    "fitpilot_token_usage_total",
    "Token 用量累计",
    ["model", "type"],
)

INGEST_CHUNKS = Counter(
    "fitpilot_ingest_chunks_total",
    "知识入库 chunk 数",
    ["format"],
)

SANITIZE_REJECT = Counter(
    "fitpilot_sanitize_reject_total",
    "输入消毒拒绝次数",
    ["reason"],
)


@contextmanager
def timed_histogram(histogram: Histogram, **labels: str) -> Generator[None, None, None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        histogram.labels(**labels).observe(time.perf_counter() - start)
