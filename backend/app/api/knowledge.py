"""知识库：集合、入库、检索。"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import fail, get_current_user, get_request_id, ok, require_role
from app.core.config import get_settings
from app.core.upload_security import validate_upload
from app.models.user import User
from app.rag import describe_rag_stack
from app.rag.context import build_context
from app.rag.ingest import ingest_directory, ingest_paths, ingest_text_document
from app.rag.parsing import describe_formats, supported_suffixes
from app.rag.retrieve import hybrid_retrieve
from app.services.qdrant_client import get_qdrant_service

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+")


class IngestDirRequest(BaseModel):
    path: str = Field(description="知识原文目录，相对仓库或绝对路径")
    version_id: str = "v1"


class IngestTextRequest(BaseModel):
    document_id: str
    title: str
    text: str = Field(min_length=1)
    version_id: str = "v1"


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int | None = None


@router.post("/collections/ensure")
async def ensure_collection(
    request: Request,
    user: User = Depends(require_role("admin")),
) -> dict:
    svc = get_qdrant_service()
    svc.ensure_collection()
    return ok(
        get_request_id(request),
        {
            "collection": get_settings().qdrant_collection,
            "vector_size": svc.vector_size,
            "embedding_model": get_settings().embedding_model,
            "status": "ready",
            "stack": describe_rag_stack(),
        },
    )


@router.get("/status")
async def knowledge_status(request: Request) -> dict:
    settings = get_settings()
    qdrant = get_qdrant_service().health()
    return ok(
        get_request_id(request),
        {
            "embedding_model": settings.resolved_embedding_model,
            "reranker_model": settings.resolved_reranker_model,
            "rag_top_k": settings.rag_top_k,
            "rag_rerank_top_k": settings.rag_rerank_top_k,
            "qdrant": qdrant,
            "stack": describe_rag_stack(),
            "supported_suffixes": supported_suffixes(),
        },
    )


@router.get("/formats")
async def knowledge_formats(request: Request) -> dict:
    """列出当前已注册的可入库文件格式。"""
    return ok(
        get_request_id(request),
        {
            "suffixes": supported_suffixes(),
            "formats": describe_formats(),
            "notes": {
                "ocr": "图片默认不 OCR；设 RAG_ENABLE_OCR=true 并安装 pytesseract/easyocr",
                "limits": "RAG_CSV_MAX_ROWS / RAG_JSON_MAX_ITEMS / RAG_PDF_MAX_PAGES / RAG_JSON_MAX_BYTES",
            },
        },
    )


@router.post("/ingest")
async def ingest(
    body: IngestDirRequest,
    request: Request,
    user: User = Depends(require_role("admin")),
) -> JSONResponse:
    rid = get_request_id(request)
    root = Path(body.path)
    if not root.is_absolute():
        root = get_settings().project_root / body.path
    result = await ingest_directory(root, version_id=body.version_id)
    return JSONResponse(ok(rid, result))


@router.post("/ingest/text")
async def ingest_text(
    body: IngestTextRequest,
    request: Request,
    user: User = Depends(require_role("admin")),
) -> JSONResponse:
    rid = get_request_id(request)
    result = await ingest_text_document(
        document_id=body.document_id,
        title=body.title,
        text=body.text,
        version_id=body.version_id,
    )
    return JSONResponse(ok(rid, result))


@router.post("/ingest/upload")
async def ingest_upload(
    request: Request,
    user: User = Depends(require_role("admin")),
    file: UploadFile = File(...),
    version_id: str = "v1",
) -> JSONResponse:
    """上传任意已支持格式文件并立即入库。"""
    rid = get_request_id(request)
    name = Path(file.filename or "upload.bin").name
    suffix = Path(name).suffix.lower()
    if suffix not in set(supported_suffixes()):
        return JSONResponse(
            status_code=400,
            content=fail(
                rid,
                "UNSUPPORTED_FORMAT",
                f"不支持的格式 {suffix}，可用：{', '.join(supported_suffixes())}",
            ),
        )
    safe = _SAFE_NAME.sub("_", Path(name).stem)[:80] + suffix
    data = await file.read()
    ok_upload, err = validate_upload(
        filename=name,
        data=data,
        allowed_suffixes=set(supported_suffixes()),
    )
    if not ok_upload:
        return JSONResponse(status_code=400, content=fail(rid, "UPLOAD_REJECTED", err or "上传被拒绝"))
    dest_dir = get_settings().project_root / "knowledge_base" / "raw" / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe
    dest.write_bytes(data)
    result = await ingest_paths([dest], version_id=version_id)
    result["saved_as"] = str(dest)
    return JSONResponse(ok(rid, result))


@router.post("/search")
async def search(
    body: SearchRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> JSONResponse:
    rid = get_request_id(request)
    chunks = await hybrid_retrieve(body.query, top_k=body.top_k)
    packed = build_context(chunks)
    return JSONResponse(ok(rid, packed))
