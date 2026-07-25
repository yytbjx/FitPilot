"""评估结果写入 Postgres。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.eval.full_eval import FullEvalReport
from app.models.evaluation import EvaluationCase, EvaluationResult, EvaluationRun


async def persist_eval_report(
    db: AsyncSession,
    report: FullEvalReport,
    *,
    run_name: str = "full_eval",
    config_path: str | None = None,
) -> int:
    row = EvaluationRun(
        run_name=run_name,
        config_path=config_path,
        ok=report.ok,
        summary=report.summary_text(),
        report_json={
            "layers": [
                {
                    "layer": l.layer,
                    "title": l.title,
                    "ok": l.ok,
                    "summary": l.summary,
                    "metrics": l.metrics,
                }
                for l in report.layers
            ],
            "ok": report.ok,
        },
        completed_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.flush()

    for layer in report.layers:
        db.add(
            EvaluationResult(
                run_id=row.id,
                layer=layer.layer,
                title=layer.title,
                ok=layer.ok,
                summary=layer.summary,
                metrics=layer.metrics,
            )
        )
        for case in layer.metrics.get("cases") or []:
            if not isinstance(case, dict):
                continue
            db.add(
                EvaluationCase(
                    run_id=row.id,
                    layer=layer.layer,
                    case_id=str(case.get("id") or ""),
                    ok=bool(case.get("ok") or case.get("correct")),
                    metrics={k: v for k, v in case.items() if k not in {"id", "ok", "correct"}},
                    detail=case,
                )
            )
    await db.commit()
    return int(row.id)
