#!/usr/bin/env python3
"""FitPilot 备份：Postgres dump + Qdrant 快照元数据 + BM25 索引。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings


def _pg_url_sync(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql://")


def backup(out_dir: Path) -> Path:
    settings = get_settings()
    root = settings.project_root
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = out_dir / f"fitpilot_backup_{ts}"
    dest.mkdir(parents=True, exist_ok=True)

    pg_file = dest / "postgres.sql"
    pg_url = _pg_url_sync(settings.database_url)
    subprocess.run(
        ["pg_dump", pg_url, "-f", str(pg_file)],
        check=False,
        capture_output=True,
    )

    bm25 = root / "knowledge_base" / "bm25_index.json"
    if bm25.exists():
        shutil.copy2(bm25, dest / "bm25_index.json")

    meta = {
        "created_at": ts,
        "qdrant_url": settings.qdrant_url,
        "qdrant_collection": settings.qdrant_collection,
        "note": "Qdrant 卷数据请通过 docker volume 或 qdrant snapshot API 另行备份",
    }
    (dest / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Backup written to {dest}")
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description="FitPilot backup")
    parser.add_argument("--out", type=Path, default=None, help="输出目录")
    args = parser.parse_args()
    settings = get_settings()
    out = args.out or (settings.project_root / "backups")
    backup(out)


if __name__ == "__main__":
    main()
