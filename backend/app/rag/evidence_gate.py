"""Evidence Gate：独立证据质量评估（增强方案 5.5）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.rag import RetrievedChunk


class EvidenceAssessment(BaseModel):
    answerable: bool
    confidence: float = 0.0
    coverage: float = 0.0
    conflicts: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    selected_evidence: list[dict[str, Any]] = Field(default_factory=list)
    reason: str | None = None
    authority_ok: bool = True


def assess_evidence(
    chunks: list[RetrievedChunk],
    *,
    query: str = "",
    min_hits: int = 1,
    min_top_score: float = 0.01,
    authority_threshold: int | None = None,
) -> EvidenceAssessment:
    """评估检索证据是否足以回答。"""
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
            )

    if top < min_top_score and all(s <= 0 for s in scores):
        return EvidenceAssessment(
            answerable=False,
            confidence=confidence,
            coverage=coverage,
            reason="LOW_CONFIDENCE",
            selected_evidence=[_brief(c) for c in usable[:4]],
        )

    conflicts: list[str] = []
    # 粗略冲突：同一查询下正负相关混杂且分差大
    if len(scores) >= 2 and (max(scores) - min(scores)) > 5 and min(scores) < 0 < max(scores):
        conflicts.append("score_polarity_conflict")

    answerable = confidence >= 0.35 and not conflicts
    return EvidenceAssessment(
        answerable=answerable,
        confidence=round(confidence, 4),
        coverage=round(coverage, 4),
        conflicts=conflicts,
        reason=None if answerable else "WEAK_EVIDENCE",
        authority_ok=authority_ok,
        selected_evidence=[_brief(c) for c in usable[:6]],
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
