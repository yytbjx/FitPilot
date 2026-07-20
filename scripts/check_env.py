"""环境连通与硬件选型自检脚本。

运行：uv run python ../scripts/check_env.py（在 backend 目录）
或：  py -3 scripts/check_env.py（项目根目录，需已安装依赖）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 保证可导入 backend.app
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def main() -> int:
    import httpx

    report: dict = {"project_root": str(ROOT)}

    # ---------- GPU / PyTorch ----------
    try:
        import torch

        cuda = torch.cuda.is_available()
        gpu = {
            "torch": torch.__version__,
            "cuda_available": cuda,
            "torch_cuda": getattr(torch.version, "cuda", None),
        }
        if cuda:
            p = torch.cuda.get_device_properties(0)
            mem_gb = p.total_memory / (1024**3)
            gpu.update({"name": p.name, "memory_gb": round(mem_gb, 2)})
            # 6GB 档选型建议
            if mem_gb < 8:
                gpu["model_policy"] = {
                    "llm": "qwen3.5:4b (Ollama Q4)",
                    "embedding": "BAAI/bge-small-zh-v1.5",
                    "reranker": "BAAI/bge-reranker-base",
                    "avoid": "勿同时在 GPU 加载 7B+ LLM 与 BGE-M3",
                }
        report["gpu"] = gpu
    except Exception as exc:  # noqa: BLE001
        report["gpu"] = {"error": str(exc)}

    # ---------- Ollama ----------
    try:
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=5.0)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        report["ollama"] = {"ok": True, "models": models}
    except Exception as exc:  # noqa: BLE001
        report["ollama"] = {"ok": False, "error": str(exc)}

    # ---------- Qdrant ----------
    try:
        r = httpx.get("http://127.0.0.1:6333/readyz", timeout=5.0)
        report["qdrant"] = {"ok": r.status_code == 200, "status_code": r.status_code}
    except Exception as exc:  # noqa: BLE001
        report["qdrant"] = {"ok": False, "error": str(exc)}

    # ---------- Docker ----------
    try:
        import subprocess

        out = subprocess.check_output(["docker", "ps", "--format", "{{.Names}}"], text=True)
        report["docker"] = {"ok": True, "containers": [x for x in out.splitlines() if x]}
    except Exception as exc:  # noqa: BLE001
        report["docker"] = {"ok": False, "error": str(exc)}

    print(json.dumps(report, ensure_ascii=False, indent=2))
    # 关键依赖失败则非 0
    critical_ok = report.get("ollama", {}).get("ok") and report.get("qdrant", {}).get("ok")
    return 0 if critical_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
