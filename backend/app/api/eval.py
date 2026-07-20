"""评估运行查询 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import fail, get_request_id, ok, require_role
from app.db.session import get_db
from app.models.evaluation import EvaluationCase, EvaluationResult, EvaluationRun
from app.models.user import User

router = APIRouter(prefix="/eval", tags=["eval"])


@router.get("/runs")
async def list_runs(
    request: Request,
    limit: int = 20,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    rows = (
        await db.scalars(
            select(EvaluationRun).order_by(EvaluationRun.id.desc()).limit(min(limit, 100))
        )
    ).all()
    return JSONResponse(
        ok(
            rid,
            {
                "items": [
                    {
                        "id": r.id,
                        "run_name": r.run_name,
                        "ok": r.ok,
                        "summary": (r.summary or "")[:200],
                        "started_at": r.started_at.isoformat() if r.started_at else None,
                        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                    }
                    for r in rows
                ]
            },
        )
    )


@router.get("/runs/{run_id}")
async def get_run(
    run_id: int,
    request: Request,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    rid = get_request_id(request)
    row = await db.scalar(select(EvaluationRun).where(EvaluationRun.id == run_id))
    if not row:
        return JSONResponse(status_code=404, content=fail(rid, "NOT_FOUND", "评估运行不存在"))
    results = (
        await db.scalars(select(EvaluationResult).where(EvaluationResult.run_id == run_id))
    ).all()
    cases = (
        await db.scalars(
            select(EvaluationCase).where(EvaluationCase.run_id == run_id).limit(500)
        )
    ).all()
    return JSONResponse(
        ok(
            rid,
            {
                "run": {
                    "id": row.id,
                    "run_name": row.run_name,
                    "ok": row.ok,
                    "summary": row.summary,
                    "config_path": row.config_path,
                    "report_json": row.report_json,
                },
                "results": [
                    {
                        "layer": r.layer,
                        "title": r.title,
                        "ok": r.ok,
                        "summary": r.summary,
                        "metrics": r.metrics,
                    }
                    for r in results
                ],
                "cases": [
                    {
                        "layer": c.layer,
                        "case_id": c.case_id,
                        "ok": c.ok,
                        "metrics": c.metrics,
                    }
                    for c in cases
                ],
            },
        )
    )
