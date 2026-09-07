"""评测进度条：CLI 交互终端显示 tqdm；CI/pytest/非 TTY 默认关闭。

环境变量：
  FITPILOT_EVAL_PROGRESS=1  强制开启
  FITPILOT_EVAL_PROGRESS=0  强制关闭
"""

from __future__ import annotations

import os
import sys
from typing import Iterable, Iterator, Sequence, TypeVar

T = TypeVar("T")


def eval_progress_enabled() -> bool:
    flag = (os.environ.get("FITPILOT_EVAL_PROGRESS") or "").strip().lower()
    if flag in {"0", "false", "off", "no"}:
        return False
    if flag in {"1", "true", "on", "yes"}:
        return True
    try:
        return bool(sys.stderr.isatty())
    except Exception:  # noqa: BLE001
        return False


def layer_banner(layer: str, title: str) -> None:
    """多层编排时打印层标题（stderr）。"""
    if not eval_progress_enabled():
        return
    print(f"\n=== eval: {layer} — {title} ===", file=sys.stderr, flush=True)


def track_cases(
    cases: Iterable[T] | Sequence[T],
    *,
    desc: str,
    total: int | None = None,
) -> Iterator[T]:
    """包装用例迭代器；启用时显示 tqdm 进度条。"""
    if isinstance(cases, Sequence) and not isinstance(cases, (str, bytes)):
        items: Sequence[T] = cases
        n = total if total is not None else len(items)
    else:
        items = list(cases)
        n = total if total is not None else len(items)

    if not eval_progress_enabled() or n == 0:
        yield from items
        return
    try:
        from tqdm import tqdm
    except ImportError:
        yield from items
        return

    yield from tqdm(
        items,
        desc=desc,
        total=n,
        unit="case",
        leave=True,
        dynamic_ncols=True,
        mininterval=0.2,
        file=sys.stderr,
    )
