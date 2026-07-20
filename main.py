"""仓库根目录短命令入口。

用法（在 FitPilot 根目录）：

  python main.py web          # 前端 Vite（:5173）
  python main.py api          # 后端 FastAPI（:8000）
  python main.py eval         # RAG 评估
  python main.py status --local
  python main.py help

说明：`web` 表示 Web 前端；后端 API 请用 `api`（不再用 web 启动后端）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def _backend_python() -> list[str]:
    venv_py = BACKEND / ".venv" / "Scripts" / "python.exe"
    if venv_py.exists():
        return [str(venv_py)]
    venv_py2 = BACKEND / ".venv" / "bin" / "python"
    if venv_py2.exists():
        return [str(venv_py2)]
    return [sys.executable]


def _run_backend_cli(args: list[str]) -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND)
    env.setdefault("NO_PROXY", "127.0.0.1,localhost")
    cmd = _backend_python() + [str(BACKEND / "main.py"), *args]
    return subprocess.call(cmd, cwd=str(BACKEND), env=env)


def _run_web(extra: list[str]) -> int:
    pnpm = shutil.which("pnpm")
    if not pnpm:
        print("未找到 pnpm，请先安装：https://pnpm.io/")
        return 1
    return subprocess.call([pnpm, "start", *extra], cwd=str(FRONTEND))


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in {"-h", "--help", "help"}:
        print(__doc__)
        print("前端：web | ui（ui 为 web 别名）")
        print("后端：api（`web` 不再用于后端；旧命令 `python main.py web` 若指后端请改 api）")
        print("运维：migrate | worker | backup | restore | seed-foods | seed-exercises | ingest | eval | eval-all | eval-no-answer | eval-agent | status | test")
        return

    cmd = args[0]
    rest = args[1:]

    if cmd in {"web", "ui", "dev", "frontend"}:
        raise SystemExit(_run_web(rest))

    if cmd == "web-legacy-api":
        warnings.warn("请使用 `python main.py api` 启动后端", DeprecationWarning)
        raise SystemExit(_run_backend_cli(["api", *rest]))

    # 兼容：若有人仍用根目录 python main.py 传后端子命令
    if cmd == "web" and os.environ.get("FITPILOT_CLI_LEGACY_API") == "1":
        raise SystemExit(_run_backend_cli(["api", *rest]))

    raise SystemExit(_run_backend_cli([cmd, *rest]))


if __name__ == "__main__":
    main()
