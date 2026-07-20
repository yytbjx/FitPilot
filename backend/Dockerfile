# FitPilot 后端镜像（交付阶段使用）
# 基础镜像含 CUDA 运行时需按部署机调整；开发期推荐宿主机 uv 热重载

FROM python:3.11-slim

WORKDIR /app

# 系统依赖（异步 Postgres 驱动编译兜底）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv 并同步锁定依赖
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml README.md ./
COPY app ./app

RUN uv sync --no-dev --no-install-project || uv pip install --system -e .

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000

# 生产入口：无 --reload
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
