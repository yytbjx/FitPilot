"""KV Cache 友好的上下文装配：稳定前缀 + Append-Only + 检索后置 + Token 预算路径优化。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from app.agents.memory.conversation_memory import MemoryFragment, estimate_tokens
from app.tools.registry import list_tools


# 稳定前缀版本号：仅在约束/工具/权限边界变更时递增，避免无谓前缀分叉
STABLE_PREFIX_VERSION = "v1"


@dataclass(frozen=True)
class AssembledBlock:
    kind: str  # stable_prefix | core | state | recall | query | evidence
    text: str
    tokens: int = 0

    def __post_init__(self) -> None:
        if self.tokens <= 0 and self.text:
            object.__setattr__(self, "tokens", estimate_tokens(self.text))


@dataclass
class AssemblyResult:
    blocks: list[AssembledBlock] = field(default_factory=list)
    selected_fragments: list[MemoryFragment] = field(default_factory=list)
    total_tokens: int = 0
    baseline_tokens: int = 0
    reduction_ratio: float = 0.0
    lcp_ratio: float = 1.0
    prefix_divergence_cost: float = 0.0
    messages: list[dict[str, str]] = field(default_factory=list)
    system_prompt: str = ""
    user_prompt: str = ""

    def to_metrics(self) -> dict[str, Any]:
        return {
            "total_tokens": self.total_tokens,
            "baseline_tokens": self.baseline_tokens,
            "reduction_ratio": round(self.reduction_ratio, 4),
            "lcp_ratio": round(self.lcp_ratio, 4),
            "prefix_divergence_cost": round(self.prefix_divergence_cost, 4),
            "selected_turns": [f.turn_index for f in self.selected_fragments],
            "stable_prefix_version": STABLE_PREFIX_VERSION,
        }


def build_stable_prefix(
    *,
    user_id: int | None = None,
    permission_note: str | None = None,
) -> str:
    """模型约束 + 高复用工具边界 + 权限边界（顺序固定，内容稳定）。"""
    tools = list_tools()
    tool_lines = []
    for t in tools:
        gate = "需审批" if t.requires_approval else "免审批"
        tool_lines.append(f"- {t.name} ({t.operation_type}, {gate})")
    tools_block = "\n".join(tool_lines) if tool_lines else "- （无已注册工具）"
    uid = f"user_id={user_id}" if user_id is not None else "user_id=unknown"
    perm = permission_note or "写操作必须经人工审批；不做疾病诊断；证据不足须拒答。"
    return (
        f"[FitPilot Stable Prefix {STABLE_PREFIX_VERSION}]\n"
        "你是 FitPilot 健身助手。仅依据给定证据与授权数据回答。\n"
        "约束：不做疾病诊断；不编造未提供的数据；高风险请求进入安全拦截。\n"
        f"权限边界：{perm}\n"
        f"身份：{uid}\n"
        "高复用工具与审批门：\n"
        f"{tools_block}"
    )


def _fragment_text(frag: MemoryFragment, *, use_summary: bool = True) -> str:
    body = frag.summary if use_summary and frag.summary else frag.content
    return f"[t{frag.turn_index}/{frag.role}] {body}"


def select_fragments_path(
    candidates: Sequence[MemoryFragment],
    *,
    token_budget: int,
    lambda_len: float = 0.02,
    lambda_gap: float = 0.05,
    lambda_fork: float = 0.03,
    prefer_contiguous_with: Sequence[int] | None = None,
) -> tuple[list[MemoryFragment], float]:
    """带 Token 预算的有序路径优化（动态规划）。

    maximize Σ rel_i·x_i
            - λ1·Σ (len_i/budget)·x_i
            - λ2·Σ gap_{i,j}·x_i·x_j
            - λ3·prefix_divergence_cost
    s.t. Σ len_i·x_i ≤ TokenBudget，保持时间序。
    """
    items = sorted(candidates, key=lambda f: f.turn_index)
    if not items or token_budget <= 0:
        return [], 0.0

    preferred = set(prefer_contiguous_with or [])
    budget = max(1, token_budget)
    best_paths: list[tuple[float, int, list[int]]] = []

    for i, frag in enumerate(items):
        tok = max(1, frag.tokens or estimate_tokens(frag.summary or frag.content))
        rel = float(frag.score)
        len_cost = lambda_len * (tok / budget) * 10.0  # 归一化到约 0–数十分
        fork = 0.0
        if preferred and frag.turn_index not in preferred:
            gap_pref = min(abs(frag.turn_index - p) for p in preferred)
            fork = lambda_fork * float(min(gap_pref, 8))
        solo = rel - len_cost - fork
        if tok > token_budget:
            best_paths.append((-1e18, 0, []))
            continue
        best = (solo, tok, [i])
        for j in range(i):
            prev_score, prev_tok, prev_idx = best_paths[j]
            if not prev_idx:
                continue
            gap = items[i].turn_index - items[prev_idx[-1]].turn_index - 1
            gap = max(0, gap)
            new_tok = prev_tok + tok
            if new_tok > token_budget:
                continue
            score = prev_score + rel - len_cost - lambda_gap * min(gap, 8) - fork
            if score > best[0]:
                best = (score, new_tok, prev_idx + [i])
        best_paths.append(best)

    winner: tuple[float, int, list[int]] = (-1e18, 0, [])
    for cand in best_paths:
        if cand[2] and cand[0] > winner[0]:
            winner = cand
    chosen = [items[i] for i in winner[2]]
    divergence = 0.0
    if preferred and chosen:
        for f in chosen:
            if f.turn_index not in preferred:
                divergence += lambda_fork
    return chosen, divergence


def longest_common_prefix_ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i / max(len(a), len(b))


def assemble_context(
    *,
    query: str,
    core: Sequence[MemoryFragment],
    recall_candidates: Sequence[MemoryFragment],
    evidence: str | None = None,
    user_id: int | None = None,
    token_budget: int = 4096,
    previous_prefix: str | None = None,
    state_note: str | None = None,
) -> AssemblyResult:
    """固定装配顺序：
    [稳定前缀] → [近期活跃 Append-Only] → [必要状态] → [召回历史(路径优化)] → [当前问题] → [证据后置]
    """
    prefix = build_stable_prefix(user_id=user_id)
    blocks: list[AssembledBlock] = [AssembledBlock(kind="stable_prefix", text=prefix)]

    # 活跃层优先完整保留
    core_sorted = sorted(core, key=lambda f: f.turn_index)
    core_budget_used = 0
    for frag in core_sorted:
        text = _fragment_text(frag, use_summary=False)
        tok = estimate_tokens(text)
        blocks.append(AssembledBlock(kind="core", text=text, tokens=tok))
        core_budget_used += tok

    if state_note:
        blocks.append(AssembledBlock(kind="state", text=f"[状态] {state_note}"))

    remain = max(64, token_budget - sum(b.tokens for b in blocks) - estimate_tokens(query) - 64)
    # 排除已在 core 的 turn；低相关直接裁剪
    core_turns = {f.turn_index for f in core_sorted}
    raw_candidates = [f for f in recall_candidates if f.turn_index not in core_turns]
    candidates = [f for f in raw_candidates if float(f.score) >= 0.2]
    selected, divergence = select_fragments_path(
        candidates,
        token_budget=remain,
        prefer_contiguous_with=[f.turn_index for f in core_sorted],
    )
    for frag in selected:
        text = _fragment_text(frag, use_summary=True)
        blocks.append(AssembledBlock(kind="recall", text=text))

    blocks.append(AssembledBlock(kind="query", text=f"当前问题：{query}"))
    if evidence:
        blocks.append(AssembledBlock(kind="evidence", text=f"证据：\n{evidence}"))

    total = sum(b.tokens for b in blocks)
    all_history = list(core_sorted) + list(raw_candidates)
    selected_ids = {f.turn_index for f in selected} | {f.turn_index for f in core_sorted}
    history_full = sum(estimate_tokens(f.content) for f in all_history) or 1
    history_used = 0
    for f in all_history:
        if f.turn_index not in selected_ids:
            continue
        # core 保留原文；召回用摘要（体现压缩收益）
        if f.turn_index in core_turns:
            history_used += estimate_tokens(f.content)
        else:
            history_used += estimate_tokens(f.summary or f.content)
    reduction = max(0.0, (history_full - history_used) / history_full)
    baseline = estimate_tokens(prefix) + history_full + estimate_tokens(query) + (
        estimate_tokens(evidence) if evidence else 0
    )

    system = prefix
    # user 侧：活跃 + 状态 + 召回 + 问题 + 证据（动态后置）
    user_parts = [b.text for b in blocks if b.kind != "stable_prefix"]
    user_prompt = "\n\n".join(user_parts)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]

    lcp = longest_common_prefix_ratio(previous_prefix or prefix, prefix)
    return AssemblyResult(
        blocks=blocks,
        selected_fragments=list(selected),
        total_tokens=total,
        baseline_tokens=baseline,
        reduction_ratio=max(0.0, reduction),
        lcp_ratio=lcp,
        prefix_divergence_cost=divergence,
        messages=messages,
        system_prompt=system,
        user_prompt=user_prompt,
    )
