"""评测进程内设备加速：仅影响当前 CLI 评测进程，不改 .env / 不改 API 默认。

策略：
- ``auto``：CUDA 可用且显存余量足够时，给 Embedding / Reranker 开 cuda；
  余量只够放小模型时仅 Embedding 上 GPU；否则保持 cpu。
- ``cuda`` / ``cpu``：强制指定（cuda 不可用时回退 cpu 并说明原因）。

离线门禁（哈希向量）不调用本模块，故不受影响。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

EvalDeviceMode = Literal["auto", "cpu", "cuda"]

# GTX 1660 Ti 6GB 量级经验阈值（MiB free）
_BOTH_MIN_FREE_MIB = 3000
_EMBED_ONLY_MIN_FREE_MIB = 700


@dataclass(frozen=True)
class EvalDevicePlan:
    mode: EvalDeviceMode
    embedding_device: str
    reranker_device: str
    reason: str
    cuda_available: bool
    free_vram_mib: int | None = None
    total_vram_mib: int | None = None

    def summary_text(self) -> str:
        vram = ""
        if self.free_vram_mib is not None and self.total_vram_mib is not None:
            vram = f" vram_free={self.free_vram_mib}MiB/{self.total_vram_mib}MiB"
        return (
            f"eval_device mode={self.mode} "
            f"embedding={self.embedding_device} reranker={self.reranker_device}"
            f"{vram} :: {self.reason}"
        )


def cuda_probe() -> tuple[bool, int | None, int | None]:
    """返回 (available, free_mib, total_mib)。探测失败视为不可用。"""
    try:
        import torch

        if not torch.cuda.is_available():
            return False, None, None
        free_b, total_b = torch.cuda.mem_get_info(0)
        return True, int(free_b // (1024 * 1024)), int(total_b // (1024 * 1024))
    except Exception:  # noqa: BLE001 — 评测加速探测失败应安静回退
        return False, None, None


def plan_eval_devices(mode: EvalDeviceMode = "auto") -> EvalDevicePlan:
    """根据模式与显存情况规划 Embedding/Reranker 设备。"""
    available, free_mib, total_mib = cuda_probe()

    if mode == "cpu":
        return EvalDevicePlan(
            mode=mode,
            embedding_device="cpu",
            reranker_device="cpu",
            reason="强制 cpu",
            cuda_available=available,
            free_vram_mib=free_mib,
            total_vram_mib=total_mib,
        )

    if mode == "cuda":
        if not available:
            return EvalDevicePlan(
                mode=mode,
                embedding_device="cpu",
                reranker_device="cpu",
                reason="请求 cuda 但当前不可用，回退 cpu",
                cuda_available=False,
                free_vram_mib=free_mib,
                total_vram_mib=total_mib,
            )
        return EvalDevicePlan(
            mode=mode,
            embedding_device="cuda",
            reranker_device="cuda",
            reason="强制 cuda（加载失败时各模型仍会自行回退 cpu）",
            cuda_available=True,
            free_vram_mib=free_mib,
            total_vram_mib=total_mib,
        )

    # auto
    if not available or free_mib is None:
        return EvalDevicePlan(
            mode="auto",
            embedding_device="cpu",
            reranker_device="cpu",
            reason="CUDA 不可用，保持 cpu（与日常 API 一致）",
            cuda_available=False,
            free_vram_mib=free_mib,
            total_vram_mib=total_mib,
        )

    if free_mib >= _BOTH_MIN_FREE_MIB:
        return EvalDevicePlan(
            mode="auto",
            embedding_device="cuda",
            reranker_device="cuda",
            reason=f"空闲显存充足（>={_BOTH_MIN_FREE_MIB}MiB），Embedding+Reranker 使用 cuda",
            cuda_available=True,
            free_vram_mib=free_mib,
            total_vram_mib=total_mib,
        )

    if free_mib >= _EMBED_ONLY_MIN_FREE_MIB:
        return EvalDevicePlan(
            mode="auto",
            embedding_device="cuda",
            reranker_device="cpu",
            reason=(
                f"空闲显存有限（{free_mib}MiB）：仅 Embedding 用 cuda，"
                f"Reranker 保持 cpu 以免 OOM"
            ),
            cuda_available=True,
            free_vram_mib=free_mib,
            total_vram_mib=total_mib,
        )

    return EvalDevicePlan(
        mode="auto",
        embedding_device="cpu",
        reranker_device="cpu",
        reason=f"空闲显存不足（{free_mib}MiB < {_EMBED_ONLY_MIN_FREE_MIB}MiB），保持 cpu",
        cuda_available=True,
        free_vram_mib=free_mib,
        total_vram_mib=total_mib,
    )


def _reset_model_singletons() -> None:
    """清空懒加载单例，确保后续按新 device 重新加载。"""
    import app.rag.embeddings as emb
    import app.rag.rerank as rr

    with emb._model_lock:
        emb._model = None
        emb._load_error = None
    emb.embedding_dim.cache_clear()

    with rr._reranker_lock:
        rr._reranker = None
        rr._load_error = None


def apply_eval_device_accel(mode: EvalDeviceMode = "auto") -> EvalDevicePlan:
    """规划并写入当前进程 Settings（不改磁盘 .env）。"""
    plan = plan_eval_devices(mode)
    settings = get_settings()
    settings.embedding_device = plan.embedding_device
    settings.reranker_device = plan.reranker_device
    _reset_model_singletons()
    logger.info(
        "eval_device_accel",
        mode=plan.mode,
        embedding_device=plan.embedding_device,
        reranker_device=plan.reranker_device,
        reason=plan.reason,
        free_vram_mib=plan.free_vram_mib,
        total_vram_mib=plan.total_vram_mib,
    )
    return plan
