"""进程内 BM25 索引。"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

_TOKEN = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_\-+%]+")


def tokenize(text: str) -> list[str]:
    """简易中英混合切词：汉字单字 + 英文词。"""
    return [t.lower() for t in _TOKEN.findall(text or "")]


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_ids: list[str] = []
        self.docs: list[list[str]] = []
        self.doc_len: list[int] = []
        self.avgdl = 0.0
        self.df: dict[str, int] = defaultdict(int)
        self.payloads: dict[str, dict] = {}

    def build(self, items: Iterable[tuple[str, str, dict]]) -> None:
        self.doc_ids.clear()
        self.docs.clear()
        self.doc_len.clear()
        self.df = defaultdict(int)
        self.payloads = {}
        for doc_id, text, payload in items:
            toks = tokenize(text)
            self.doc_ids.append(doc_id)
            self.docs.append(toks)
            self.doc_len.append(len(toks))
            self.payloads[doc_id] = payload
            for t in set(toks):
                self.df[t] += 1
        n = len(self.docs) or 1
        self.avgdl = sum(self.doc_len) / n

    def search(self, query: str, top_k: int = 8) -> list[tuple[str, float]]:
        q = tokenize(query)
        if not q or not self.docs:
            return []
        scores: list[tuple[str, float]] = []
        n = len(self.docs)
        for i, toks in enumerate(self.docs):
            tf = Counter(toks)
            score = 0.0
            dl = self.doc_len[i] or 1
            for term in q:
                if term not in tf:
                    continue
                df = self.df.get(term, 0) or 1
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                freq = tf[term]
                denom = freq + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                score += idf * (freq * (self.k1 + 1)) / denom
            if score > 0:
                scores.append((self.doc_ids[i], float(score)))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "doc_ids": self.doc_ids,
            "docs": self.docs,
            "doc_len": self.doc_len,
            "avgdl": self.avgdl,
            "df": dict(self.df),
            "payloads": self.payloads,
            "k1": self.k1,
            "b": self.b,
        }
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "BM25Index":
        raw = json.loads(path.read_text(encoding="utf-8"))
        idx = cls(k1=raw.get("k1", 1.5), b=raw.get("b", 0.75))
        idx.doc_ids = raw["doc_ids"]
        idx.docs = raw["docs"]
        idx.doc_len = raw["doc_len"]
        idx.avgdl = raw["avgdl"]
        idx.df = defaultdict(int, raw["df"])
        idx.payloads = raw["payloads"]
        return idx


_GLOBAL: BM25Index | None = None


def _index_path() -> Path:
    from app.core.config import get_settings

    return get_settings().project_root / "knowledge_base" / "bm25_index.json"


def get_bm25_index() -> BM25Index:
    global _GLOBAL
    path = _index_path()
    if _GLOBAL is None:
        if path.exists():
            _GLOBAL = BM25Index.load(path)
        else:
            _GLOBAL = BM25Index()
    return _GLOBAL


def persist_bm25(index: BM25Index) -> None:
    global _GLOBAL
    _GLOBAL = index
    index.save(_index_path())
