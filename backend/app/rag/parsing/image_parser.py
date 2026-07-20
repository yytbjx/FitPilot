"""图片：优先可选 OCR，否则写结构化占位 + 旁路同名说明。"""

from __future__ import annotations

import os
from pathlib import Path

from app.rag.parsing.base import ParseResult
from app.rag.parsing.registry import register


def _sidecar_text(path: Path) -> str | None:
    for ext in (".md", ".txt"):
        side = path.with_suffix(ext)
        if side.exists() and side.is_file():
            try:
                return side.read_text(encoding="utf-8", errors="ignore").strip()
            except Exception:
                return None
    return None


def _try_ocr(path: Path) -> str | None:
    if os.getenv("RAG_ENABLE_OCR", "false").lower() not in {"1", "true", "yes", "on"}:
        return None
    lang = os.getenv("RAG_OCR_LANG", "chi_sim+eng")
    # 1) pytesseract + Pillow
    try:
        from PIL import Image  # type: ignore
        import pytesseract  # type: ignore

        img = Image.open(path)
        text = pytesseract.image_to_string(img, lang=lang)
        text = (text or "").strip()
        return text or None
    except Exception:
        pass
    # 2) easyocr（较重，可选）
    try:
        import easyocr  # type: ignore

        langs = ["ch_sim", "en"] if "chi" in lang or "ch" in lang else ["en"]
        reader = easyocr.Reader(langs, gpu=False)
        result = reader.readtext(str(path), detail=0, paragraph=True)
        text = "\n".join(result).strip()
        return text or None
    except Exception:
        return None


@register(".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff")
def parse_image(path: Path) -> ParseResult:
    parts: list[str] = [f"# 图片资料：{path.stem}", "", f"- 文件: `{path.name}`", f"- 路径: `{path}`"]

    try:
        from PIL import Image  # type: ignore

        with Image.open(path) as img:
            parts.append(f"- 尺寸: {img.size[0]}x{img.size[1]}")
            parts.append(f"- 模式: {img.mode}")
    except Exception:
        parts.append("- 元信息: 未能读取（可安装 Pillow）")

    ocr = _try_ocr(path)
    side = _sidecar_text(path)
    if ocr:
        parts.append("\n## OCR 文本\n")
        parts.append(ocr)
    if side:
        parts.append("\n## 旁路说明（同名 md/txt）\n")
        parts.append(side)
    if not ocr and not side:
        parts.append(
            "\n## 说明\n"
            "当前未提取到图片文字。可任选：\n"
            "1. 放置同名 `.md` / `.txt` 说明；\n"
            "2. 安装 OCR 依赖后设置 `RAG_ENABLE_OCR=true`（pytesseract 或 easyocr）。\n"
        )

    return ParseResult(
        title=path.stem,
        text="\n".join(parts),
        format="image",
        metadata={"ocr": bool(ocr), "sidecar": bool(side)},
    )
