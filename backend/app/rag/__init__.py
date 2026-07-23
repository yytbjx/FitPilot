"""RAG 子系统公共类型与栈说明。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class DocumentChunk:
    document_id: str
    version_id: str
    chunk_id: str
    text: str
    title: str = ""
    section_path: str = ""
    source_path: str = ""
    evidence_level: str = "general"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "version_id": self.version_id,
            "chunk_id": self.chunk_id,
            "text": self.text,
            "title": self.title,
            "section_path": self.section_path,
            "source_path": self.source_path,
            "evidence_level": self.evidence_level,
            **self.metadata,
        }


@dataclass
class RetrievedChunk:
    chunk_id: str
    text: str
    score: float
    title: str = ""
    section_path: str = ""
    source_path: str = ""
    document_id: str = ""
    version_id: str = ""
    citation: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def describe_rag_stack() -> dict[str, str]:
    return {
        "embedding": "BAAI/bge-small-zh-v1.5",
        "reranker": "BAAI/bge-reranker-base",
        "dense_store": "Qdrant",
        "sparse": "BM25 in-process",
        "fusion": "RRF",
        "chunking": "doc-type aware (fixed/heading/parent-child/faq/clause/table) + A/B compare",
        "query": "rewrite + Multi-Query + query_type/entities/time_range",
        "citations": "mapped evidence with coverage + index_version",
        "parsing": "multi-format registry (md/docx/pdf/html/csv/json/xlsx/pptx/image…)",
    }
