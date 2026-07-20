"""应用配置：通过 Pydantic Settings 从环境变量 / .env 加载并校验。

设计要点：
- 开发、测试、生产使用独立配置；密钥不得写入代码仓库。
- 模型名、Token 预算等与验收指标相关的参数也在此版本化管理。
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """FitPilot 全局配置（全部字段带中文语义说明）。"""

    model_config = SettingsConfigDict(
        # 从 backend 启动时优先读上级目录 .env，其次当前目录
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- 应用基础 ----------
    app_name: str = Field(default="FitPilot", description="应用名称")
    app_env: Literal["development", "test", "production"] = Field(
        default="development", description="运行环境"
    )
    app_debug: bool = Field(default=True, description="是否开启调试")
    app_host: str = Field(default="0.0.0.0", description="监听地址")
    app_port: int = Field(default=8000, description="监听端口")

    # ---------- JWT ----------
    jwt_secret: str = Field(default="change-me", description="JWT 签名密钥")
    jwt_algorithm: str = Field(default="HS256", description="JWT 算法")
    jwt_expire_minutes: int = Field(default=60, description="访问令牌有效期（分钟）")
    refresh_token_expire_days: int = Field(default=14, description="Refresh Token 有效期（天）")

    # ---------- Worker ----------
    agent_use_worker: bool = Field(
        default=False,
        description="为 True 时 Agent 任务入 Redis 队列，由独立 worker 消费",
    )

    # ---------- 食谱优化 ----------
    meal_use_ortools: bool = Field(
        default=True,
        description="为 True 时优先使用 OR-Tools 约束优化；失败则回退贪心",
    )

    # ---------- PostgreSQL ----------
    database_url: str = Field(
        default="postgresql+asyncpg://fitpilot:fitpilot@127.0.0.1:5432/fitpilot",
        description="异步数据库连接串",
    )

    # ---------- Redis ----------
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", description="Redis 连接串")

    # ---------- Qdrant（向量库，连接本机 Docker） ----------
    qdrant_url: str = Field(default="http://127.0.0.1:6333", description="Qdrant HTTP 地址")
    qdrant_collection: str = Field(default="fitpilot_knowledge", description="默认集合名")
    qdrant_api_key: str | None = Field(default=None, description="Qdrant API Key（可选）")

    # ---------- Ollama（本机大模型服务；按环节分模型以省显存） ----------
    ollama_base_url: str = Field(default="http://127.0.0.1:11434", description="Ollama API 根地址")
    ollama_model: str = Field(
        default="qwen2.5:1.5b",
        description="默认/回退模型；6GB 显存推荐 1.5B，质量优先可改 qwen3.5:4b",
    )
    ollama_model_rag: str = Field(
        default="",
        description="RAG 知识问答生成模型；空则回退 ollama_model",
    )
    ollama_model_judge: str = Field(
        default="qwen2.5:0.5b",
        description="LLM-as-judge / 结构化打分；用最小模型省显存",
    )
    ollama_model_rewrite: str = Field(
        default="qwen2.5:0.5b",
        description="查询改写（可选 LLM）；空则仅用规则改写",
    )
    ollama_model_classify: str = Field(
        default="qwen2.5:0.5b",
        description="意图分类辅助（可选）；默认仍用规则，开启 ollama_use_llm_classify 才调用",
    )
    ollama_use_llm_rewrite: bool = Field(
        default=False,
        description="为 True 时用小模型做查询改写（略增延迟，省显存用 0.5B）",
    )
    ollama_use_llm_classify: bool = Field(
        default=False,
        description="为 True 时规则无法判定时用小模型辅助意图分类",
    )
    ollama_keep_alive: str = Field(
        default="30s",
        description="Ollama keep_alive；短时间卸载模型释放显存（如 0 / 30s / 5m）",
    )
    ollama_timeout_seconds: float = Field(default=120.0, description="Ollama 请求超时（秒）")

    # ---------- Embedding / Reranker（按显存选型） ----------
    embedding_model: str = Field(
        default="",
        description="Embedding 模型；本地路径或 HuggingFace 名；空则使用 <项目根>/models/bge-small-zh-v1.5",
    )
    embedding_device: str = Field(
        default="cpu",
        description="Embedding 推理设备；与 Ollama 同卡时建议 cpu，避免抢 6GB 显存",
    )
    reranker_model: str = Field(
        default="",
        description="Reranker 模型；空则使用 <项目根>/models/bge-reranker-large",
    )
    reranker_device: str = Field(default="cpu", description="Reranker 推理设备；与 Ollama 错峰可用 cpu")
    rag_top_k: int = Field(default=8, description="混合检索召回条数")
    rag_rerank_top_k: int = Field(default=4, description="精排后保留条数")
    rag_skip_rerank: bool = Field(
        default=False,
        description="为 True 时跳过 Reranker，直接取 RRF 前 N 条（显著提速，略降精准度）",
    )

    # ---------- Token 预算监控 ----------
    token_budget: int = Field(
        default=100_000,
        description="Token 总预算（prompt + completion），用于成本与过载保护",
    )
    token_stop_ratio: float = Field(
        default=0.5,
        description="用量达到预算的该比例时自动停止（默认 50%）",
        ge=0.01,
        le=1.0,
    )

    # ---------- 日志 ----------
    log_level: str = Field(default="INFO", description="日志级别")

    @field_validator("token_stop_ratio")
    @classmethod
    def _ratio_ok(cls, v: float) -> float:
        """保证停止比例合法。"""
        if not 0 < v <= 1:
            raise ValueError("token_stop_ratio 必须在 (0, 1] 内")
        return v

    @property
    def project_root(self) -> Path:
        """仓库根目录（backend 的上一级）。"""
        return Path(__file__).resolve().parents[2]

    @property
    def resolved_embedding_model(self) -> str:
        if self.embedding_model and str(self.embedding_model).strip():
            return str(self.embedding_model)
        local = self.project_root / "models" / "bge-small-zh-v1.5"
        return str(local) if local.exists() else "BAAI/bge-small-zh-v1.5"

    @property
    def resolved_reranker_model(self) -> str:
        if self.reranker_model and str(self.reranker_model).strip():
            return str(self.reranker_model)
        for name in ("bge-reranker-large", "bge-reranker-base"):
            local = self.project_root / "models" / name
            if local.exists():
                return str(local)
        return "BAAI/bge-reranker-base"

    @property
    def token_stop_threshold(self) -> int:
        """计算自动停止的 Token 绝对阈值。"""
        return int(self.token_budget * self.token_stop_ratio)

    def resolve_ollama_model(self, role: str = "default") -> str:
        """按环节解析 Ollama 模型名（空字段回退到 ollama_model）。

        角色：
        - default：通用回退
        - rag：知识问答生成（质量要求最高）
        - judge：评估裁判（结构化短输出）
        - rewrite：查询改写
        - classify：意图辅助分类
        """
        role = (role or "default").strip().lower()
        mapping = {
            "default": self.ollama_model,
            "rag": self.ollama_model_rag or self.ollama_model,
            "judge": self.ollama_model_judge or self.ollama_model,
            "rewrite": self.ollama_model_rewrite or self.ollama_model_judge or self.ollama_model,
            "classify": self.ollama_model_classify or self.ollama_model_judge or self.ollama_model,
        }
        name = mapping.get(role) or self.ollama_model
        return str(name).strip() or self.ollama_model

    def ollama_model_roles(self) -> dict[str, str]:
        """返回各环节实际生效的模型名（便于 status / 启动日志）。"""
        return {
            "default": self.resolve_ollama_model("default"),
            "rag": self.resolve_ollama_model("rag"),
            "judge": self.resolve_ollama_model("judge"),
            "rewrite": self.resolve_ollama_model("rewrite"),
            "classify": self.resolve_ollama_model("classify"),
        }


@lru_cache
def get_settings() -> Settings:
    """缓存单例配置，避免重复读取环境变量。"""
    return Settings()
