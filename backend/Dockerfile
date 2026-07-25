# FitPilot 后端镜像（交付阶段使用）
#
# 构建上下文必须是【仓库根目录】（docker-compose.prod.yml 中 context: .），
# 因为镜像内还需要仓库根的 alembic.ini 与 migrations/ 才能执行 `alembic upgrade head`。
# 镜像内目录布局与仓库一致：
#   /srv/alembic.ini        script_location=migrations, prepend_sys_path=backend
#   /srv/migrations/        Alembic 版本目录
#   /srv/backend/           应用代码 + .venv
#   /srv/models/            （可选）本地 Embedding/Reranker 权重，建议运行时挂载

# ---------- 构建阶段：用 uv 按 uv.lock 锁定安装 ----------
FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /srv/backend

# uv：字节码预编译 + 拷贝模式（跨阶段 COPY .venv 需要）
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# 只拷贝锁文件与元数据，先装第三方依赖（最大化利用构建缓存）
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-default-groups --no-install-project --no-editable

# 再拷贝应用代码并安装项目本身（非 editable，依赖与项目全部锁定）
COPY backend/app ./app
COPY backend/main.py ./main.py
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-default-groups --no-editable

# ---------- 运行阶段：slim + 非 root ----------
FROM python:3.11-slim

ENV TZ=Asia/Shanghai \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/srv/backend/.venv/bin:$PATH" \
    PYTHONPATH="/srv/backend"

# 时区数据（slim 镜像不含 tzdata）
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system fitpilot && useradd --system --gid fitpilot --create-home fitpilot

WORKDIR /srv

# 从构建阶段拷贝已锁定的虚拟环境
COPY --from=builder /srv/backend/.venv /srv/backend/.venv

# 应用代码与迁移资产（非 editable 安装后仍保留源码，便于 alembic/env.py import app.models）
COPY backend/pyproject.toml /srv/backend/pyproject.toml
COPY backend/app /srv/backend/app
COPY backend/main.py /srv/backend/main.py
COPY alembic.ini /srv/alembic.ini
COPY migrations /srv/migrations

# 模型缓存目录（运行时建议挂载 ./models 与 HF 缓存，避免镜像膨胀）
RUN mkdir -p /srv/models /home/fitpilot/.cache \
    && chown -R fitpilot:fitpilot /srv /home/fitpilot

USER fitpilot

EXPOSE 8000

# slim 镜像无 curl，用 python urllib 探测轻量健康端点（app.main 同时把 router 挂在根路径）
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# 生产入口：无 --reload；在 /srv（仓库根布局）下启动，alembic/CLI 均可用
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
