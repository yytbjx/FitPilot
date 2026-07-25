"""入库 knowledge_base/raw；可选重建 Qdrant 集合。

用法：
  python scripts/ingest_kb.py
  python scripts/ingest_kb.py --reset   # 仅清空向量库 fitpilot_knowledge，不动 Postgres 用户数据
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(k, None)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset",
        action="store_true",
        help="重建 Qdrant 知识集合（不影响 Postgres 用户/计划数据）",
    )
    parser.add_argument(
        "--path",
        default=str(ROOT / "knowledge_base" / "raw"),
        help="语料根目录",
    )
    args = parser.parse_args()

    from app.core.config import get_settings
    from app.rag.bm25 import BM25Index, persist_bm25
    from app.rag.embeddings import embedding_dim
    from app.rag.ingest import ingest_directory
    from app.services.qdrant_client import get_qdrant_service

    get_settings.cache_clear()
    if args.reset:
        svc = get_qdrant_service()
        svc.reset_collection(vector_size=embedding_dim())
        # 同步清空本地 BM25
        persist_bm25(BM25Index())
        print("qdrant_collection_reset_and_bm25_cleared")

    result = await ingest_directory(Path(args.path), version_id="v2")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
