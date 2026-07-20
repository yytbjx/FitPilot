#!/usr/bin/env python3
"""FitPilot 恢复：从 backup 目录还原 Postgres + BM25 索引。"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from app.core.config import get_settings


def _pg_url_sync(async_url: str) -> str:
    return async_url.replace("postgresql+asyncpg://", "postgresql://")


def restore(backup_dir: Path) -> None:
    settings = get_settings()
    root = settings.project_root
    manifest = backup_dir / "manifest.json"
    if manifest.exists():
        print(json.loads(manifest.read_text(encoding="utf-8")))

    pg_file = backup_dir / "postgres.sql"
    if pg_file.exists():
        pg_url = _pg_url_sync(settings.database_url)
        subprocess.run(["psql", pg_url, "-f", str(pg_file)], check=False)
        print(f"Restored Postgres from {pg_file}")

    bm25_src = backup_dir / "bm25_index.json"
    if bm25_src.exists():
        bm25_dst = root / "knowledge_base" / "bm25_index.json"
        bm25_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(bm25_src, bm25_dst)
        print(f"Restored BM25 index to {bm25_dst}")


def main() -> None:
    parser = argparse.ArgumentParser(description="FitPilot restore")
    parser.add_argument("backup_dir", type=Path, help="备份目录路径")
    args = parser.parse_args()
    if not args.backup_dir.exists():
        raise SystemExit(f"not found: {args.backup_dir}")
    restore(args.backup_dir)


if __name__ == "__main__":
    main()
