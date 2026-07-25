"""Evidence Gate：全站唯一的证据质量/拒答判定（增强方案 5.5，迭代 3 收敛）。

设计要点：
- 拒答判定收敛到本模块单套逻辑；`rag.context.build_context` 复用本模块结果，
  不再维护第二套阈值（迭代 3 前两者条件不一致：confidence>=0.35 vs top_score<-2.0）。
- 分数体系显式区分：RRF 融合分（恒正、0.01 量级）与 CrossEncoder 精排原始分
  （可正可负、量级大）。冲突检测与弱精排判定只在 rerank 分体系下生效；
  RRF 分传入时跳过（迭代 3 前 (max-min)>5 的阈值对 RRF 分永不触发，形同虚设）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.rag import RetrievedChunk

# RRF 融合分上限经验值：单路 RRF(k=60) 最大 1/61≈0.016，多查询变体叠加也很难超过 0.5；
# CrossEncoder 原始分（logits）常见量级 ±10。超过该上限即视为 rerank 分体系。
_RRF_SCORE_CEILING = 0.5
# 冲突检测的分差阈值，仅对 CrossEncoder 原始分有意义
_CONFLICT_SPREAD = 5.0


class EvidenceAssessment(BaseModel):
    answerable: bool
    confidence: float = 0.0
    coverage: float = 0.0
    conflicts: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    selected_evidence: list[dict[str, Any]] = Field(default_factory=list)
    reason: str | None = None
    authority_ok: bool = True
    # 迭代 3 新增（带默认值，向后兼容）：分数体系 rrf / rerank / unknown
    score_scale: str = "unknown"


def score_scale_of(scores: list[float]) -> str:
    """判别分数体系：rerank（CrossEncoder 原始分）/ rrf（融合分）/ unknown。"""
    if not scores:
        return "unknown"
    lo, hi = min(scores), max(scores)
    if lo < 0 or hi > _RRF_SCORE_CEILING:
        return "rerank"
    return "rrf"


def assess_evidence(
    chunks: list[RetrievedChunk],
    *,
    query: str = "",
    min_hits: int = 1,
    min_top_score: float = 0.01,
    authority_threshold: int | None = None,
    min_confidence: float | None = None,
    rerank_min_score: float | None = None,
) -> EvidenceAssessment:
    """评估检索证据是否足以回答（全站唯一拒答判定入口）。

    min_confidence / rerank_min_score 传 None 时读取全局 settings
    （rag_evidence_min_confidence / rag_rerank_min_score）。
    """
    if min_confidence is None or rerank_min_score is None:
        from app.core.config import get_settings

        settings = get_settings()
        if min_confidence is None:
            min_confidence = float(settings.rag_evidence_min_confidence)
        if rerank_min_score is None:
            rerank_min_score = float(settings.rag_rerank_min_score)

    usable = [c for c in chunks if (c.text or "").strip()]
    if len(usable) < min_hits:
        return EvidenceAssessment(
            answerable=False,
            confidence=0.0,
            coverage=0.0,
            reason="NO_EVIDENCE",
            selected_evidence=[],
        )

    scores = [float(c.score or 0.0) for c in usable]
    scale = score_scale_of(scores)
    top = max(scores) if scores else 0.0
    avg = sum(scores) / len(scores) if scores else 0.0
    # 简单覆盖：命中条数归一化到 4
    coverage = min(1.0, len(usable) / 4.0)
    confidence = max(0.0, min(1.0, 0.5 * _squash(top) + 0.3 * _squash(avg) + 0.2 * coverage))

    authority_ok = True
    if authority_threshold is not None:
        levels = []
        for c in usable:
            meta = c.metadata or {}
            levels.append(int(meta.get("authority_level") or 0))
        authority_ok = any(lv >= authority_threshold for lv in levels)
        if not authority_ok:
            return EvidenceAssessment(
                answerable=False,
                confidence=confidence,
                coverage=coverage,
                reason="LOW_AUTHORITY",
                authority_ok=False,
                selected_evidence=[_brief(c) for c in usable[:4]],
                score_scale=scale,
            )

    if top < min_top_score and all(s <= 0 for s in scores):
        return EvidenceAssessment(
            answerable=False,
            confidence=confidence,
            coverage=coverage,
            reason="LOW_CONFIDENCE",
            selected_evidence=[_brief(c) for c in usable[:4]],
            score_scale=scale,
        )

    # 弱精排：仅 rerank 分体系下，top 分低于阈值视为弱证据（RRF 分恒正，跳过）
    if scale == "rerank" and top < rerank_min_score:
        return EvidenceAssessment(
            answerable=False,
            confidence=confidence,
            coverage=coverage,
            reason="LOW_CONFIDENCE",
            selected_evidence=[_brief(c) for c in usable[:4]],
            score_scale=scale,
        )

    conflicts: list[str] = []
    # 粗略冲突：同一查询下正负相关混杂且分差大。
    # 仅对 CrossEncoder 原始分有意义；RRF 分恒正且量级小，显式跳过。
    if (
        scale == "rerank"
        and len(scores) >= 2
        and (max(scores) - min(scores)) > _CONFLICT_SPREAD
        and min(scores) < 0 < max(scores)
    ):
        conflicts.append("score_polarity_conflict")

    answerable = confidence >= min_confidence and not conflicts
    return EvidenceAssessment(
        answerable=answerable,
        confidence=round(confidence, 4),
        coverage=round(coverage, 4),
        conflicts=conflicts,
        reason=None if answerable else ("CONFLICTING_EVIDENCE" if conflicts else "WEAK_EVIDENCE"),
        authority_ok=authority_ok,
        selected_evidence=[_brief(c) for c in usable[:6]],
        score_scale=scale,
    )


def _squash(x: float) -> float:
    # 将任意分数压到 0..1（对 RRF 小正数与 rerank 负数都较稳）
    if x >= 0:
        return min(1.0, x / (x + 0.05))
    return max(0.0, 1.0 / (1.0 + abs(x)))


def _brief(c: RetrievedChunk) -> dict[str, Any]:
    return {
        "chunk_id": c.chunk_id,
        "document_id": c.document_id,
        "title": c.title,
        "section_path": c.section_path,
        "score": c.score,
        "citation": c.citation,
        "text_preview": (c.text or "")[:180],
        "authority_level": (c.metadata or {}).get("authority_level"),
    }
