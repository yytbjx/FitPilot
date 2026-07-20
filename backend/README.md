# FitPilot 后端

## CLI 语义（重要）

| 命令 | 含义 |
|------|------|
| **`api`** | 启动 FastAPI 后端（:8000） |
| `web` | **已废弃**（曾误用于后端）；请改用 `api` |
| `migrate` / `seed-*` / `ingest` / `eval` / `status` / `test` | 运维与验收 |

前端 Web 请在**仓库根目录**执行：`python main.py web`

## 短命令启动

在 `backend` 目录：

```powershell
uv sync
uv run python main.py api          # 启动 API :8000
uv run fitpilot api

uv run python main.py migrate
uv run python main.py seed-exercises
uv run python main.py seed-foods
uv run python main.py ingest
uv run python main.py ingest --reset
uv run python main.py eval
uv run python main.py status --local
uv run python main.py test
```

仓库根目录：

```powershell
python main.py api      # 后端
python main.py web      # 前端
python main.py eval
```

- Swagger：http://127.0.0.1:8000/docs  
- 推荐 API 前缀：`/api/v1/`（旧路径仍兼容）
