"""知识库上传安全校验（工程审查 P0）。"""

from __future__ import annotations

import mimetypes
from pathlib import Path

# 默认 20MB
DEFAULT_MAX_BYTES = 20 * 1024 * 1024

_BLOCKED_SUFFIXES = {
    ".exe",
    ".bat",
    ".cmd",
    ".ps1",
    ".sh",
    ".dll",
    ".msi",
    ".js",
    ".vbs",
    ".jar",
    ".zip",
    ".rar",
    ".7z",
}

_ALLOWED_MIME_PREFIXES = (
    "text/",
    "application/pdf",
    "application/json",
    "application/vnd.",
    "application/msword",
    "application/vnd.openxmlformats",
    "image/",
)


def validate_upload(
    *,
    filename: str,
    data: bytes,
    allowed_suffixes: set[str],
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> tuple[bool, str | None]:
    name = Path(filename or "upload.bin").name
    if ".." in name or name.startswith("."):
        return False, "非法文件名"
    suffix = Path(name).suffix.lower()
    if suffix in _BLOCKED_SUFFIXES:
        return False, f"禁止上传的类型：{suffix}"
    if suffix not in allowed_suffixes:
        return False, f"不支持的格式 {suffix}"
    if len(data) == 0:
        return False, "空文件"
    if len(data) > max_bytes:
        return False, f"文件超过大小限制({max_bytes // (1024 * 1024)}MB)"
    mime, _ = mimetypes.guess_type(name)
    if mime and not any(mime.startswith(p) for p in _ALLOWED_MIME_PREFIXES):
        return False, f"不允许的 MIME 类型：{mime}"
    # 简单魔数：PDF
    if suffix == ".pdf" and not data.startswith(b"%PDF"):
        return False, "PDF 文件头校验失败"
    return True, None
