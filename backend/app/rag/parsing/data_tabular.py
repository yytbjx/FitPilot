"""CSV / TSV / JSON / JSONL 结构化数据 → Markdown。"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any

from app.rag.parsing.base import ParseError, ParseResult
from app.rag.parsing.registry import register


def _max_rows() -> int:
    return int(os.getenv("RAG_CSV_MAX_ROWS", "300") or "300")


def _max_json_items() -> int:
    return int(os.getenv("RAG_JSON_MAX_ITEMS", "200") or "200")


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    esc_h = [h.replace("|", "\\|") or " " for h in headers]
    lines = [
        "| " + " | ".join(esc_h) + " |",
        "| " + " | ".join("---" for _ in esc_h) + " |",
    ]
    for row in rows:
        cells = [
            (row[i] if i < len(row) else "").replace("|", "\\|").replace("\n", " ")[:200]
            for i in range(len(esc_h))
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _open_text(path: Path):
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.open(encoding=enc, newline="")
        except UnicodeDecodeError:
            continue
    return path.open(encoding="utf-8", errors="ignore", newline="")


@register(".csv", ".tsv")
def parse_delimited(path: Path) -> ParseResult:
    delim = "\t" if path.suffix.lower() == ".tsv" else ","
    max_rows = _max_rows()
    with _open_text(path) as f:
        # 嗅探 dialect（失败则按 delim）
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            reader = csv.reader(f, dialect)
        except csv.Error:
            reader = csv.reader(f, delimiter=delim)
        rows = list(reader)
    if not rows:
        raise ParseError("csv_empty")
    headers = [str(c) for c in rows[0]]
    data = [[str(c) for c in r] for r in rows[1 : 1 + max_rows]]
    note = ""
    if len(rows) - 1 > max_rows:
        note = f"\n\n> 已截断：共 {len(rows) - 1} 行，仅入库前 {max_rows} 行（RAG_CSV_MAX_ROWS）\n"
    text = f"# {path.stem}\n\n" + _md_table(headers, data) + note
    return ParseResult(
        title=path.stem,
        text=text,
        format=path.suffix.lower().lstrip("."),
        metadata={"rows": min(len(rows) - 1, max_rows), "cols": len(headers)},
    )


def _flatten_obj(obj: Any, prefix: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)) and not isinstance(v, str):
                out.extend(_flatten_obj(v, key))
            else:
                out.append((key, str(v)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:50]):
            key = f"{prefix}[{i}]"
            if isinstance(v, (dict, list)):
                out.extend(_flatten_obj(v, key))
            else:
                out.append((key, str(v)))
    else:
        out.append((prefix or "value", str(obj)))
    return out


def _json_to_markdown(data: Any, *, title: str) -> str:
    max_items = _max_json_items()
    parts = [f"# {title}"]

    if isinstance(data, list):
        parts.append(f"数组长度: {len(data)}（展示前 {min(len(data), max_items)} 项）")
        # 若是对象数组且字段较齐，做成表
        sample = [x for x in data[:max_items] if isinstance(x, dict)]
        if sample and len(sample) >= max(1, len(data[:max_items]) // 2):
            keys: list[str] = []
            for obj in sample:
                for k in obj.keys():
                    if k not in keys and not isinstance(obj[k], (dict, list)):
                        keys.append(str(k))
                if len(keys) >= 12:
                    break
            if keys:
                rows = []
                for obj in sample:
                    rows.append(["" if obj.get(k) is None else str(obj.get(k))[:200] for k in keys])
                parts.append(_md_table(keys, rows))
                return "\n\n".join(parts)
        for i, item in enumerate(data[:max_items]):
            parts.append(f"## Item {i + 1}")
            if isinstance(item, dict):
                for k, v in _flatten_obj(item)[:40]:
                    parts.append(f"- **{k}**: {v}")
            else:
                parts.append(str(item))
        return "\n\n".join(parts)

    if isinstance(data, dict):
        # 常见包装：FoundationFoods / items / data
        for wrap_key in ("items", "FoundationFoods", "data", "records", "results"):
            if isinstance(data.get(wrap_key), list):
                parts.append(f"字段 `{wrap_key}`：")
                parts.append(_json_to_markdown(data[wrap_key], title=f"{title}/{wrap_key}"))
                # 其它顶层标量元数据
                meta = {k: v for k, v in data.items() if k != wrap_key and not isinstance(v, (dict, list))}
                if meta:
                    parts.append("## Metadata")
                    for k, v in meta.items():
                        parts.append(f"- **{k}**: {v}")
                return "\n\n".join(parts)
        parts.append("## Fields")
        for k, v in _flatten_obj(data)[:200]:
            parts.append(f"- **{k}**: {v}")
        return "\n\n".join(parts)

    return f"# {title}\n\n{data}"


@register(".json")
def parse_json(path: Path) -> ParseResult:
    # 超大文件保护（默认 8MB）
    max_bytes = int(os.getenv("RAG_JSON_MAX_BYTES", str(8 * 1024 * 1024)))
    size = path.stat().st_size
    if size > max_bytes:
        raise ParseError(f"json_too_large:{size}>{max_bytes}")
    text_raw = path.read_text(encoding="utf-8-sig", errors="ignore")
    try:
        data = json.loads(text_raw)
    except json.JSONDecodeError as exc:
        raise ParseError(f"json_invalid:{exc}") from exc
    md = _json_to_markdown(data, title=path.stem)
    if len(md) < 20:
        raise ParseError("json_empty")
    return ParseResult(title=path.stem, text=md, format="json", metadata={"bytes": size})


@register(".jsonl", ".ndjson")
def parse_jsonl(path: Path) -> ParseResult:
    max_items = _max_json_items()
    items: list[Any] = []
    with path.open(encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(items) >= max_items:
                break
    if not items:
        raise ParseError("jsonl_empty")
    md = _json_to_markdown(items, title=path.stem)
    return ParseResult(title=path.stem, text=md, format="jsonl", metadata={"items": len(items)})
