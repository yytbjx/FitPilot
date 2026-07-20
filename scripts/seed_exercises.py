"""导入 exercises-dataset 到 Postgres，并可选写入 Qdrant（RAG）。

用法:
  cd D:\\FitPilot
  $env:PYTHONPATH="D:\\FitPilot\\backend"
  .\\backend\\.venv\\Scripts\\python.exe scripts\\seed_exercises.py
  .\\backend\\.venv\\Scripts\\python.exe scripts\\seed_exercises.py --to-qdrant
  .\\backend\\.venv\\Scripts\\python.exe scripts\\seed_exercises.py --limit 50  # 调试
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from qdrant_client.http import models as qm
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import get_engine
from app.models.exercise import Exercise
from app.rag.bm25 import BM25Index, get_bm25_index, persist_bm25
from app.rag.chunking import split_text
from app.rag.embeddings import embed_texts
from app.services.exercise_seed import (
    default_dataset_path,
    exercise_to_rag_text,
    load_dataset,
    upsert_exercises,
)
from app.services.qdrant_client import get_qdrant_service
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def seed_postgres(limit: int | None) -> dict:
    rows = load_dataset()
    if limit:
        rows = rows[:limit]
    engine = get_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:  # type: AsyncSession
        result = await upsert_exercises(db, rows)
        count = await db.scalar(select(func.count()).select_from(Exercise))
        result["db_count"] = int(count or 0)
        result["source"] = str(default_dataset_path())
        return result


async def seed_qdrant(limit: int | None, batch_size: int = 32) -> dict:
    """批量写入动作说明到知识库（一次重建 BM25，避免逐条极慢）。"""
    settings = get_settings()
    svc = get_qdrant_service()
    svc.ensure_collection(vector_size=512)

    engine = get_engine()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:  # type: AsyncSession
        stmt = select(Exercise).order_by(Exercise.id)
        if limit:
            stmt = stmt.limit(limit)
        rows = (await db.scalars(stmt)).all()

    all_chunks = []
    for ex in rows:
        text = exercise_to_rag_text(ex)
        title = ex.name_zh or ex.name_en
        chunks = split_text(
            text,
            document_id=f"exercise_{ex.external_id}",
            version_id="exercises-dataset-v1",
            title=f"动作/{title}",
            source_path=f"exercises-dataset:{ex.external_id}",
        )
        all_chunks.extend(chunks)

    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i : i + batch_size]
        vectors = embed_texts([c.text for c in batch])
        points = [
            qm.PointStruct(
                id=str(uuid5(NAMESPACE_URL, f"{c.document_id}:{c.version_id}:{c.chunk_id}")),
                vector=vectors[j],
                payload=c.to_payload(),
            )
            for j, c in enumerate(batch)
        ]
        svc.client.upsert(collection_name=settings.qdrant_collection, points=points)
        print(f"qdrant upsert {min(i + batch_size, len(all_chunks))}/{len(all_chunks)}")

    bm25 = get_bm25_index()
    merged = dict(bm25.payloads)
    for c in all_chunks:
        merged[c.chunk_id] = c.to_payload()
    new_index = BM25Index()
    new_index.build((cid, p.get("text", ""), p) for cid, p in merged.items())
    persist_bm25(new_index)

    return {
        "rag_documents": len(rows),
        "rag_chunks": len(all_chunks),
        "collection": settings.qdrant_collection,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed FitPilot exercises from exercises-dataset")
    parser.add_argument("--limit", type=int, default=None, help="仅导入前 N 条（调试）")
    parser.add_argument("--to-qdrant", action="store_true", help="同步写入 Qdrant RAG")
    parser.add_argument("--qdrant-only", action="store_true", help="跳过 Postgres，仅把已有 exercises 写入 Qdrant")
    args = parser.parse_args()

    if not args.qdrant_only:
        pg = await seed_postgres(args.limit)
        print("postgres:", pg)
    if args.to_qdrant or args.qdrant_only:
        rag = await seed_qdrant(args.limit)
        print("qdrant:", rag)


if __name__ == "__main__":
    asyncio.run(main())
