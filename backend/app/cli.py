"""FitPilot 后端 CLI：短命令启动与运维。

语义约定（与前端一致）：
  api   — 启动 FastAPI 后端（:8000）
  web   — 已废弃别名，请改用 api

在 backend 目录：

  uv run python main.py api
  uv run fitpilot api
"""

from __future__ import annotations

import os
import subprocess
import sys
import warnings
from pathlib import Path

import typer

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")

cli = typer.Typer(
    name="fitpilot",
    help="FitPilot 后端命令行",
    add_completion=False,
    no_args_is_help=True,
)


def _run_py(script_rel: str, *args: str) -> int:
    script = REPO_ROOT / script_rel
    cmd = [sys.executable, str(script), *args]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    return subprocess.call(cmd, cwd=str(REPO_ROOT), env=env)


def _start_api(host: str, port: int, reload: bool) -> None:
    import uvicorn

    from app.core.config import get_settings

    settings = get_settings()
    roles = settings.ollama_model_roles()
    typer.echo(
        f"FitPilot API → http://127.0.0.1:{port}/docs  "
        f"rag={roles['rag']} judge={roles['judge']} keep_alive={settings.ollama_keep_alive}"
    )
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[str(BACKEND_ROOT / "app")] if reload else None,
    )


@cli.command("api")
def api(
    host: str = typer.Option("0.0.0.0", help="监听地址"),
    port: int = typer.Option(8000, help="端口"),
    reload: bool = typer.Option(True, help="热重载（开发）"),
) -> None:
    """启动 FastAPI 后端（uvicorn）。"""
    _start_api(host, port, reload)


@cli.command("web", hidden=True)
def web_deprecated(
    host: str = typer.Option("0.0.0.0", help="监听地址"),
    port: int = typer.Option(8000, help="端口"),
    reload: bool = typer.Option(True, help="热重载（开发）"),
) -> None:
    """[已废弃] 请使用 `fitpilot api`。此前 web 误用于后端，易与前端混淆。"""
    warnings.warn(
        "CLI 命令 `web` 已废弃用于后端，请改用 `fitpilot api`；前端请用仓库根目录 `python main.py web`",
        DeprecationWarning,
        stacklevel=1,
    )
    typer.echo("提示：`web` 已废弃，请改用 `fitpilot api`")
    _start_api(host, port, reload)


@cli.command("worker")
def worker_cmd(
    poll_timeout: int = typer.Option(5, help="Redis BRPOP 超时秒数"),
) -> None:
    """启动 Agent Worker（消费 Redis 队列）。"""
    import asyncio

    from app.worker.agent_runner import worker_loop

    typer.echo("FitPilot Agent Worker 已启动（需 AGENT_USE_WORKER=true 且 API 入队）")
    asyncio.run(worker_loop(poll_timeout=poll_timeout))


@cli.command("backup")
def backup_cmd(
    out: Path = typer.Option(None, "--out", help="备份输出目录"),
) -> None:
    """备份 Postgres + BM25 索引。"""
    args: list[str] = []
    if out:
        args.extend(["--out", str(out)])
    raise SystemExit(_run_py("scripts/backup.py", *args))


@cli.command("restore")
def restore_cmd(backup_dir: Path = typer.Argument(..., help="备份目录")) -> None:
    """从备份目录恢复。"""
    raise SystemExit(_run_py("scripts/restore.py", str(backup_dir)))


@cli.command("eval-no-answer")
def eval_no_answer(
    suite: Path = typer.Option(
        REPO_ROOT / "evals" / "no_answer_cases.json",
        "--suite",
        help="无答案评测集",
    ),
) -> None:
    from app.eval.no_answer_eval import run_no_answer_eval

    result = run_no_answer_eval(suite)
    typer.echo(result.summary_text())
    raise SystemExit(0 if result.ok else 1)


@cli.command("eval-agent")
def eval_agent(
    suite: Path = typer.Option(
        REPO_ROOT / "evals" / "agent_routing_cases.json",
        "--suite",
        help="Agent 路由评测集",
    ),
) -> None:
    from app.eval.agent_eval import run_agent_eval

    result = run_agent_eval(suite)
    typer.echo(result.summary_text())
    raise SystemExit(0 if result.ok else 1)


@cli.command("eval-gate")
def eval_gate(
    config: Path = typer.Option(
        REPO_ROOT / "evals" / "eval_config.json",
        "--config",
        help="评估配置（使用 thresholds 做门禁）",
    ),
    out: Path | None = typer.Option(None, help="JSON 报告路径"),
) -> None:
    """CI 离线门禁：parsing / agent / plan / meal / safety（不依赖 Qdrant）。"""
    import json as _json

    from app.eval.ci_gate import run_ci_gates

    report = run_ci_gates(config)
    typer.echo(report.summary_text())
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(0 if report.ok else 1)


@cli.command("eval-all")
def eval_all(
    config: Path = typer.Option(
        REPO_ROOT / "evals" / "eval_config.json",
        "--config",
        help="七层评估配置",
    ),
    out: Path | None = typer.Option(None, help="JSON 报告路径"),
    md: Path | None = typer.Option(None, help="Markdown 报告路径"),
    persist: bool = typer.Option(False, "--persist", help="写入 evaluation_runs 表"),
    online: bool = typer.Option(False, "--online", help="启用 LLM-as-judge 在线评估"),
) -> None:
    """运行七层评估编排（解析/检索/拒答/生成/Agent/计划/食谱/安全）。"""
    import asyncio

    from app.eval.full_eval import run_full_eval

    if online:
        import json as _json

        cfg_path = config
        cfg = _json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        cfg.setdefault("modules", {})["generation_online"] = {"enabled": True}
        tmp = REPO_ROOT / "evals" / "reports" / "_eval_config_online.json"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(_json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        config = tmp

    out_dir = REPO_ROOT / "evals" / "reports"
    out_path = out or out_dir / "full_eval_latest.json"
    md_path = md or out_dir / "full_eval_latest.md"
    report = run_full_eval(
        config_path=config,
        repo_root=REPO_ROOT,
        out_path=out_path,
        md_path=md_path,
    )
    typer.echo(report.summary_text())
    typer.echo(f"report: {out_path}")
    if persist:
        async def _save() -> int:
            from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

            from app.db.session import get_engine
            from app.eval.eval_persistence import persist_eval_report

            factory = async_sessionmaker(get_engine(), expire_on_commit=False)
            async with factory() as db:
                return await persist_eval_report(
                    db, report, config_path=str(config)
                )

        run_id = asyncio.run(_save())
        typer.echo(f"db_run_id={run_id}")
    raise SystemExit(0 if report.ok else 1)


@cli.command("migrate")
def migrate() -> None:
    """执行 Alembic upgrade head。"""
    cfg = REPO_ROOT / "alembic.ini"
    code = subprocess.call(
        [sys.executable, "-m", "alembic", "-c", str(cfg), "upgrade", "head"],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
    )
    raise SystemExit(code)


@cli.command("seed-exercises")
def seed_exercises(
    to_qdrant: bool = typer.Option(False, "--to-qdrant", help="同步写入向量库"),
    limit: int | None = typer.Option(None, help="仅导入前 N 条"),
) -> None:
    """导入动作库到 Postgres。"""
    args: list[str] = []
    if to_qdrant:
        args.append("--to-qdrant")
    if limit is not None:
        args.extend(["--limit", str(limit)])
    raise SystemExit(_run_py("scripts/seed_exercises.py", *args))


@cli.command("seed-foods")
def seed_foods(
    prepare: bool = typer.Option(True, help="先运行 prepare_fdc_kb"),
) -> None:
    """导入中文种子 + USDA 食物宏量。"""
    if prepare:
        code = _run_py("scripts/prepare_fdc_kb.py")
        if code != 0:
            raise SystemExit(code)
    raise SystemExit(_run_py("scripts/seed_foods.py"))


@cli.command("ingest")
def ingest(
    reset: bool = typer.Option(False, "--reset", help="重建 Qdrant 知识集合（不动 Postgres）"),
    path: str | None = typer.Option(None, help="语料目录，默认 knowledge_base/raw"),
) -> None:
    """知识库多格式入库。"""
    args: list[str] = []
    if reset:
        args.append("--reset")
    if path:
        args.extend(["--path", path])
    raise SystemExit(_run_py("scripts/ingest_kb.py", *args))


@cli.command("knowledge-diff")
def knowledge_diff(
    path: Path = typer.Option(
        REPO_ROOT / "knowledge_base" / "raw",
        "--path",
        help="语料目录",
    ),
) -> None:
    """比较磁盘语料与 knowledge_sources，列出新增/变更/未变。"""
    import asyncio
    import json as _json

    from app.rag.knowledge_lifecycle import diff_knowledge_dir

    result = asyncio.run(diff_knowledge_dir(path))
    typer.echo(_json.dumps(result, ensure_ascii=False, indent=2))


@cli.command("knowledge-ingest")
def knowledge_ingest(
    incremental: bool = typer.Option(True, "--incremental/--full", help="增量或全量刷新 manifest"),
    reset: bool = typer.Option(False, "--reset", help="重建向量集合后再全量入库"),
    path: Path = typer.Option(
        REPO_ROOT / "knowledge_base" / "raw",
        "--path",
        help="语料目录",
    ),
) -> None:
    """知识入库（默认增量）；写入 knowledge_sources 与 index_versions.jsonl。"""
    import asyncio
    import json as _json

    from app.rag.knowledge_lifecycle import ingest_incremental
    from app.services.qdrant_client import get_qdrant_service

    if reset:
        get_qdrant_service().reset_collection()
    result = asyncio.run(ingest_incremental(path, reset=reset or not incremental))
    typer.echo(_json.dumps(result, ensure_ascii=False, indent=2, default=str))


@cli.command("knowledge-index-version")
def knowledge_index_version(
    list_all: bool = typer.Option(False, "--list", help="列出全部 index_version"),
) -> None:
    """查看当前 / 最近索引版本元数据。"""
    import json as _json

    from app.rag.knowledge_lifecycle import get_active_index_version, list_index_versions

    if list_all:
        vers = list_index_versions()
        typer.echo(_json.dumps(vers, ensure_ascii=False, indent=2))
        raise SystemExit(0 if vers else 1)
    ver = get_active_index_version()
    if not ver:
        typer.echo("尚无 index_version 记录")
        raise SystemExit(1)
    typer.echo(_json.dumps(ver, ensure_ascii=False, indent=2))


@cli.command("knowledge-rollback")
def knowledge_rollback(
    version: str = typer.Option(..., "--version", help="目标 index_version，如 idx_abcdef"),
    path: Path = typer.Option(
        REPO_ROOT / "knowledge_base" / "raw",
        "--path",
        help="语料目录",
    ),
    no_reset: bool = typer.Option(False, "--no-reset", help="不重建 Qdrant 集合"),
) -> None:
    """回滚到历史索引版本（按版本清单重入库）。"""
    import asyncio
    import json as _json

    from app.rag.knowledge_lifecycle import rollback_index_version

    result = asyncio.run(
        rollback_index_version(version, raw_dir=path, reset_collection=not no_reset)
    )
    typer.echo(_json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result.get("ok") else 1)


@cli.command("knowledge-snapshot")
def knowledge_snapshot(
    action: str = typer.Argument("list", help="create | list | restore"),
    name: str | None = typer.Option(None, "--name", help="restore 时快照名"),
) -> None:
    """Qdrant 知识集合快照：create / list / restore。"""
    import json as _json

    from app.services.qdrant_client import get_qdrant_service

    svc = get_qdrant_service()
    if action == "create":
        typer.echo(_json.dumps(svc.create_snapshot(), ensure_ascii=False, indent=2))
        raise SystemExit(0)
    if action == "list":
        typer.echo(_json.dumps(svc.list_snapshots(), ensure_ascii=False, indent=2))
        raise SystemExit(0)
    if action == "restore":
        if not name:
            typer.echo("--name 必填")
            raise SystemExit(2)
        result = svc.recover_snapshot(name)
        typer.echo(_json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result.get("ok") else 1)
    typer.echo("action 应为 create|list|restore")
    raise SystemExit(2)


@cli.command("seed-demo")
def seed_demo() -> None:
    """写入演示账号、档案与近两周打卡数据。"""
    raise SystemExit(_run_py("scripts/seed_demo.py"))


@cli.command("chunk-compare")
def chunk_compare(
    path: Path = typer.Option(..., "--path", help="语料文件路径"),
) -> None:
    """离线对比分块策略（fixed / heading / parent_child / faq_qa / clause）。"""
    import json as _json

    from app.rag.chunk_strategies import compare_chunk_strategies
    from app.rag.parsing import parse_file_rich

    parsed = parse_file_rich(path)
    report = compare_chunk_strategies(
        parsed.text,
        document_id=path.stem,
        title=parsed.title,
        source_path=str(path),
    )
    report["parse_format"] = parsed.format
    typer.echo(_json.dumps(report, ensure_ascii=False, indent=2))


@cli.command("eval")
def eval_cmd(
    suite: Path = typer.Option(
        REPO_ROOT / "evals" / "golden_rag.json",
        "--suite",
        help="评测集 JSON",
    ),
    top_k: int = typer.Option(4, help="检索 top_k（与 Hit@K 取更大）"),
    out: Path | None = typer.Option(None, help="结果输出 JSON 路径"),
    md: Path | None = typer.Option(None, help="Markdown 报告路径"),
    config: Path = typer.Option(
        REPO_ROOT / "evals" / "eval_config.json",
        "--config",
        help="评估配置 JSON/YAML",
    ),
) -> None:
    """运行 RAG 评估（Hit@K / MRR / 引用 / 时延）。"""
    from app.eval.rag_eval import run_rag_eval

    result = run_rag_eval(
        suite_path=suite,
        top_k=top_k,
        out_path=out,
        md_path=md,
        config_path=config if config.exists() else None,
    )
    typer.echo(result.summary_text())
    raise SystemExit(0 if result.ok else 1)


@cli.command("status")
def status(
    base_url: str = typer.Option("http://127.0.0.1:8000", help="API 根地址"),
    local: bool = typer.Option(False, "--local", help="不走 HTTP，进程内探测依赖"),
) -> None:
    """检查 Postgres / Redis / Qdrant / Ollama 就绪状态。"""
    import asyncio
    import json as _json

    api_base = base_url.rstrip("/")
    if not local and not api_base.endswith("/api/v1"):
        api_base = f"{api_base}/api/v1"

    async def _via_http() -> dict:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{api_base}/health/ready")
            r.raise_for_status()
            return r.json()

    async def _via_local() -> dict:
        from sqlalchemy import text
        from redis.asyncio import Redis

        from app.core.config import get_settings
        from app.core.token_monitor import get_token_monitor
        from app.db.session import get_engine
        from app.services.ollama_client import get_ollama_client
        from app.services.qdrant_client import get_qdrant_service

        settings = get_settings()
        checks: dict = {}
        try:
            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["postgres"] = {"ok": True}
        except Exception as exc:  # noqa: BLE001
            checks["postgres"] = {"ok": False, "error": str(exc)}
        try:
            redis = Redis.from_url(settings.redis_url, decode_responses=True)
            pong = await redis.ping()
            await redis.aclose()
            checks["redis"] = {"ok": bool(pong)}
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = {"ok": False, "error": str(exc)}
        try:
            checks["qdrant"] = get_qdrant_service().health()
        except Exception as exc:  # noqa: BLE001
            checks["qdrant"] = {"ok": False, "error": str(exc)}
        try:
            checks["ollama"] = await get_ollama_client().health()
        except Exception as exc:  # noqa: BLE001
            checks["ollama"] = {"ok": False, "error": str(exc)}
        checks["token_monitor"] = get_token_monitor().snapshot().to_dict()
        ready = all(
            isinstance(v, dict) and v.get("ok") is True
            for k, v in checks.items()
            if k in {"postgres", "redis", "qdrant", "ollama"}
        )
        return {"data": {"ready": ready, "checks": checks}}

    try:
        payload = asyncio.run(_via_local() if local else _via_http())
    except Exception as exc:  # noqa: BLE001
        if not local:
            typer.echo(f"HTTP 探测失败（{exc}），改用 --local")
            payload = asyncio.run(_via_local())
        else:
            typer.echo(f"status failed: {exc}")
            raise SystemExit(1) from exc

    data = payload.get("data") if isinstance(payload, dict) else payload
    typer.echo(_json.dumps(data, ensure_ascii=False, indent=2))
    ready = bool(isinstance(data, dict) and data.get("ready"))
    raise SystemExit(0 if ready else 1)


@cli.command("test")
def test(
    pytest_args: list[str] | None = typer.Argument(default=None),
) -> None:
    """运行 pytest（默认 -q）。"""
    args = pytest_args or ["-q"]
    raise SystemExit(
        subprocess.call(
            [sys.executable, "-m", "pytest", *args],
            cwd=str(BACKEND_ROOT),
            env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
        )
    )


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
