"""多格式解析测试。"""

from __future__ import annotations

import json
from pathlib import Path

from app.rag.chunking import chunks_from_file
from app.rag.parsing import describe_formats, parse_file_rich, supported_suffixes


def test_supported_formats_include_common():
    suffixes = set(supported_suffixes())
    for s in [".md", ".pdf", ".docx", ".csv", ".json", ".html", ".png", ".xlsx", ".pptx"]:
        assert s in suffixes
    assert describe_formats()


def test_parse_md_csv_json(tmp_path: Path):
    md = tmp_path / "a.md"
    md.write_text("# Hello\n\n蛋白质建议。", encoding="utf-8")
    r = parse_file_rich(md)
    assert "蛋白质" in r.text

    csv_path = tmp_path / "foods.csv"
    csv_path.write_text("name,kcal\n鸡胸肉,133\n米饭,116\n", encoding="utf-8")
    r2 = parse_file_rich(csv_path)
    assert "鸡胸肉" in r2.text
    assert "|" in r2.text

    js = tmp_path / "items.json"
    js.write_text(
        json.dumps({"items": [{"name": "燕麦", "kcal": 367}, {"name": "鸡蛋", "kcal": 144}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    r3 = parse_file_rich(js)
    assert "燕麦" in r3.text


def test_parse_html(tmp_path: Path):
    p = tmp_path / "page.html"
    p.write_text(
        "<html><head><title>Diet</title></head>"
        "<body><h1>Fat Loss</h1><p>Protein planning guide for athletes.</p></body></html>",
        encoding="utf-8",
    )
    r = parse_file_rich(p)
    assert r.title == "Diet"
    assert "Protein" in r.text


def test_chunks_preserve_parse_format(tmp_path: Path):
    p = tmp_path / "note.txt"
    p.write_text("力量训练恢复需要睡眠。", encoding="utf-8")
    chunks = chunks_from_file(p, version_id="t1")
    assert chunks
    assert chunks[0].metadata.get("parse_format") in {"txt", "text"}
