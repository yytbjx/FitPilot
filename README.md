# FitPilot — 个性化训练与膳食协同 AI Agent

基于《FitPilot 标准开发文档 V1.0》落地的 **阶段 1–3 MVP + 工程深化**（可本地联调、可验收、可生产交付）。

本仓库默认路径：`D:\FitPilot`（下文 PowerShell 示例可按本机路径替换）。

---

## 目录

1. [项目定位](#1-项目定位)
2. [功能全景](#2-功能全景)
3. [系统架构](#3-系统架构)
4. [技术栈与硬件选型](#4-技术栈与硬件选型)
5. [仓库目录结构](#5-仓库目录结构)
6. [数据模型与存储](#6-数据模型与存储)
7. [RAG 知识问答](#7-rag-知识问答)
8. [LangGraph Agent](#8-langgraph-agent)
9. [业务域工具与确定性计算](#9-业务域工具与确定性计算)
10. [安全、合规与输入防护](#10-安全合规与输入防护)
11. [可观测性、Trace 与 Token 预算](#11-可观测性trace-与-token-预算)
12. [知识库与数据导入管线](#12-知识库与数据导入管线)
13. [外部数据集与参考项目](#13-外部数据集与参考项目)
14. [环境变量与配置](#14-环境变量与配置)
15. [从零部署（完整命令步骤）](#15-从零部署完整命令步骤)
16. [Worker 异步任务模式](#16-worker-异步任务模式)
17. [生产环境部署](#17-生产环境部署)
18. [备份与恢复](#18-备份与恢复)
19. [CLI 命令大全](#19-cli-命令大全)
20. [REST API 参考](#20-rest-api-参考)
21. [前端页面与交互](#21-前端页面与交互)
22. [测试、七层评估与 CI](#22-测试七层评估与-ci)
23. [管理员与 RBAC](#23-管理员与-rbac)
24. [性能与延迟优化](#24-性能与延迟优化)
25. [路线图与未实现项](#25-路线图与未实现项)
26. [相关文档索引](#26-相关文档索引)

---

## 1. 项目定位

FitPilot 是面向健身与膳食场景的 **个人 AI 助手**：

- **结构化业务数据**（档案、打卡、计划、食物库、动作库）存 **PostgreSQL**，由确定性代码读写与计算。
- **非结构化知识**（指南、科普、FAQ、上传文档）经 **RAG** 入库 **Qdrant + BM25**，对话时检索证据再由 **Ollama** 组织回答并附引用。
- **Agent** 用 **LangGraph** 做意图路由、风险拦截、计划预览与 **interrupt() 人工确认**、个人数据汇总；前端通过 **SSE** 展示执行进度。
- **食谱优化** 支持 **OR-Tools SCIP** 约束求解（`MEAL_USE_ORTOOLS=true`），失败时自动贪心回退。
- **评估体系** 覆盖解析 / 检索 / 拒答 / 生成 / Agent 路由 / 计划硬约束 / 食谱 / 安全等 **九模块**，可 `--persist` 写入数据库。

**当前范围**：阶段 1–3 MVP + 工程审查 P0/P1 + LangGraph Checkpointer + Worker 队列 + 多层评估。  
**非目标**：疾病诊断、伤病治疗、教练端 SaaS、自动无确认写库。

---

## 2. 功能全景

| 模块 | 能力 | 实现要点 |
|------|------|----------|
| **账号** | 注册 / 登录 / 刷新 / 登出 | JWT + Refresh Token（`refresh_tokens` 表）；前端 Axios 401 自动续期 |
| **RBAC** | `user` / `admin` | 知识库入库、评估查询需 `admin` |
| **用户档案** | 身高体重、目标、器械、伤病、活动量 | `user_profiles`；TDEE / 宏量由 `nutrition.py` 计算 |
| **食物库** | 中文种子 + USDA Foundation | Postgres `food_items`；`source` / `external_id` 溯源 |
| **动作库** | ~1324 条 exercises-dataset | 器械×部位筛选、`POST /exercises/shuffle` |
| **打卡记录** | 训练 / 饮食 / 体测 | 饮食宏量由食物库 **确定性** 换算 |
| **训练+饮食计划** | 预览 → 确认 → 写入；回滚；Diff | 版本表 `*_plan_versions`；`plan_adjustments` 周调整记录 |
| **周联合调整** | 基于近 7 日日志诊断 | `POST /plans/weekly-adjust`；`weekly_adjust_preview` |
| **单餐换菜** | 锁定其余餐次重优化 | `POST /plans/meals/swap`；OR-Tools / 贪心 |
| **知识问答** | 混合检索 + 引用 + 拒答 | Dense + BM25 → RRF → Rerank → Ollama |
| **Agent 对话** | 多意图路由、SSE、异步任务 | LangGraph；`interrupt()` 计划确认 |
| **Agent 持久化** | 任务事件 / 步骤 / 工具调用 | `agent_task_*` 表；重启可回放 |
| **LangGraph Checkpointer** | 全状态断点续跑 | `lg_checkpoints` 等；`GET/POST .../checkpoint|resume` |
| **Worker 模式** | Redis 队列消费 | `AGENT_USE_WORKER=true` + `fitpilot worker` |
| **知识管理** | 多格式入库、上传（admin） | `ingest_kb.py` + `/knowledge/*` |
| **健康检查** | 存活 / 就绪 / Token | `/health`、`/health/ready`、`/metrics/tokens` |
| **评估** | 九模块多层评估 + RAG 黄金集 | `eval-all`、`eval`、`eval-agent` 等；`evaluation_runs` 持久化 |
| **运维** | status / backup / restore / Prometheus | CLI + `docker-compose.prod.yml` |

---

## 3. 系统架构

```text
┌─────────────┐     HTTPS/JWT      ┌──────────────────────────────────────────┐
│  Vue3 前端   │ ◄────────────────► │  FastAPI (backend/app)  /api/v1         │
│  Pinia/SSE  │   Refresh Token    │  auth / users / foods / exercises / logs  │
└─────────────┘                    │  plans / knowledge / agent / eval / health │
                                   └───────┬──────────────┬──────────┬─────────┘
                                           │              │          │
                    ┌──────────────────────┘              │          │
                    ▼                                     ▼          ▼
            ┌───────────────┐                    ┌────────────┐  ┌─────────┐
            │  PostgreSQL    │                    │   Qdrant   │  │  Ollama │
            │  用户/计划/库   │                    │  向量 chunks│  │  LLM    │
            │  Agent/评估    │                    └─────┬──────┘  └─────────┘
            └───────────────┘                          │
                    │                          ┌───────▼──────┐
            ┌───────┴───────┐                  │  BM25 本地索引 │
            │     Redis      │                  │  + Embedding │
            │  缓存/任务队列  │                  └──────────────┘
            └───────┬───────┘
                    │  AGENT_USE_WORKER=true
                    ▼
            ┌───────────────┐
            │ Agent Worker  │  BRPOP 消费 → run_fitness_agent
            └───────────────┘
```

### 3.1 对话主路径（知识问答）

1. 用户消息 → **InputSanitizer**
2. LangGraph **classify** → **rag** 节点
3. **hybrid_retrieve**：Qdrant Dense + BM25 → RRF → Reranker
4. **build_context**：证据 + citation；不足则 `no_answer`
5. **Ollama chat** → 返回 `reply` + `citations`；SSE 推送进度

### 3.2 计划主路径（含 interrupt）

1. 意图 `plan_create` / `plan_adjust` → **plan_preview**
2. `preview_and_stage_plans`：器械×部位抽动作 + 营养目标生成饮食
3. **plan_confirm** 节点调用 `interrupt()` → 任务状态 `awaiting_confirmation`
4. 前端 SSE 收到 `approval_required` → 用户 **approve/reject**
5. `POST /agent/tasks/{id}/approve` 或 `POST /plans/{id}/approve` → **plan_commit** / **plan_reject**

### 3.3 CLI 双入口

| 入口 | 路径 | 说明 |
|------|------|------|
| 根目录 | `python main.py <cmd>` | `web`/`ui`/`dev` = 前端；其余转发后端 CLI |
| 后端 | `cd backend && uv run python main.py <cmd>` | 等同 `uv run fitpilot <cmd>` |

> **约定**：`web` = 前端 Vite；`api` = 后端 FastAPI。后端 `web` 命令已废弃。

---

## 4. 技术栈与硬件选型

| 层级 | 选型 | 说明 |
|------|------|------|
| 前端 | Vue 3 + Vite + TypeScript + Pinia + Element Plus | JWT + Refresh；路由守卫 |
| 后端 | FastAPI + SQLAlchemy 2 (async) + Alembic | `asyncpg`；API 前缀 `/api/v1` |
| 编排 | LangGraph + langchain-ollama | `fitness_graph.py`；Postgres Checkpointer |
| 优化 | OR-Tools SCIP | `meal_optimizer.py`；`MEAL_USE_ORTOOLS` |
| 业务库 | PostgreSQL 16 | Docker 或生产 Compose |
| 缓存/队列 | Redis 7 | 就绪检查；Agent 任务队列 |
| 向量库 | Qdrant | 集合 `fitpilot_knowledge` |
| 稀疏检索 | 自研 BM25 | 与 Dense 做 RRF |
| 对话 LLM | Ollama（按环节分模型） | 默认 RAG=`qwen2.5:1.5b`，Judge=`qwen2.5:0.5b` |
| Embedding | `BAAI/bge-small-zh-v1.5` | 本仓库 `models/bge-small-zh-v1.5`（独立副本） |
| Reranker | `bge-reranker-large`（可换 base） | 本仓库 `models/bge-reranker-large`（独立副本，默认 **CPU**） |
| 依赖管理 | uv + pnpm | 后端 / 前端 |
| 可观测 | Prometheus + structlog | `/metrics`；可选 Grafana |

> **部署独立**：本仓库模型权重位于 `models/`，不依赖其他项目的目录联接；迁移时请一并拷贝 `models/` 与 `.env`。

### 本机硬件示例（GTX 1660 Ti 6GB）

| 组件 | 推荐 |
|------|------|
| Ollama RAG | `qwen2.5:1.5b`（质量优先可 `qwen3.5:4b`） |
| Ollama Judge / 改写 / 分类 | `qwen2.5:0.5b` |
| Embedding 设备 | **`cpu`**（与 Ollama 错峰） |
| Reranker 设备 | `cpu` |
| 显存策略 | `OLLAMA_KEEP_ALIVE=30s`；勿默认加载 `qwen2.5:7b` |

#### Ollama 分环节选型（对照本机已装模型）

| 环节 | 环境变量 | 推荐模型 | 说明 |
|------|----------|----------|------|
| RAG 生成 | `OLLAMA_MODEL_RAG` | `qwen2.5:1.5b` | 日常问答；显存够再升 `qwen3.5:4b` |
| 默认回退 | `OLLAMA_MODEL` | `qwen2.5:1.5b` | RAG 未单独配置时使用 |
| 评估裁判 | `OLLAMA_MODEL_JUDGE` | `qwen2.5:0.5b` | 短结构化输出，极省显存 |
| 查询改写 | `OLLAMA_MODEL_REWRITE` | `qwen2.5:0.5b` | 需 `OLLAMA_USE_LLM_REWRITE=true` |
| 意图辅助 | `OLLAMA_MODEL_CLASSIFY` | `qwen2.5:0.5b` | 需 `OLLAMA_USE_LLM_CLASSIFY=true`；默认仍用规则 |
| （不推荐默认） | — | `qwen2.5:7b` / `gemma3:4b` | 7B 易 OOM；gemma 中文弱于 Qwen |

```powershell
# 确保小模型已拉取
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:1.5b
# 可选：质量优先 RAG（同时把 EMBEDDING_DEVICE=cpu）
# ollama pull qwen3.5:4b
```

详见 [`docs/MODEL_DOWNLOAD.md`](docs/MODEL_DOWNLOAD.md)。

---

## 5. 仓库目录结构

```text
FitPilot/
├── main.py                      # 根目录 CLI（web=api 分离）
├── .env / .env.example          # 全局环境变量
├── docker-compose.dev.yml       # 开发：Postgres + Redis
├── docker-compose.prod.yml      # 生产：全栈 + Worker + Prometheus/Grafana
├── deploy/prometheus.yml        # 生产 Prometheus scrape
├── alembic.ini + migrations/    # 数据库迁移 0001–0007
├── scripts/
│   ├── ingest_kb.py             # 知识入库（--reset）
│   ├── seed_exercises.py        # 动作库 → Postgres
│   ├── seed_foods.py            # 食物库 → Postgres
│   ├── prepare_fdc_kb.py        # USDA 中文包 → curated/fdc
│   ├── backup.py / restore.py   # 备份恢复
│   └── check_env.py             # 环境检查
├── knowledge_base/
│   ├── raw/                     # RAG 原文（curated / external / uploads）
│   └── SOURCES.md
├── models/                      # 本地 Embedding / Reranker 权重
├── evals/                       # 评测集 + eval_config.json + reports/
├── docs/                        # 专题文档
├── backend/
│   ├── main.py                  # 后端 CLI 入口
│   ├── app/
│   │   ├── api/                 # REST 路由
│   │   ├── core/                # 配置、日志、指标、消毒、Token
│   │   ├── db/                  # 异步 Session
│   │   ├── models/              # SQLAlchemy 模型
│   │   ├── schemas/             # Pydantic
│   │   ├── services/            # Ollama、Qdrant、营养
│   │   ├── rag/                 # 解析、切块、检索、入库
│   │   ├── graphs/              # LangGraph + Checkpointer
│   │   ├── tools/               # 领域工具（白名单）
│   │   ├── eval/                # 七层评估
│   │   ├── worker/              # Agent Worker
│   │   └── cli.py               # fitpilot 子命令
│   └── tests/                   # pytest（37+ 项）
└── frontend/
    └── src/
        ├── views/               # 8 个页面
        ├── stores/              # auth（含 refresh）/ chat（SSE + approve）
        └── api/client.ts        # Axios + 401 续期
```

---

## 6. 数据模型与存储

### 6.1 存哪里

| 数据 | 存储 | 清库注意 |
|------|------|----------|
| 用户、密码、档案、Refresh Token | Postgres | **勿**为灌知识库而清 |
| 训练/饮食计划及版本 | Postgres | approve / rollback |
| 计划周调整记录 | Postgres `plan_adjustments` | 含 diagnosis / diff |
| 训练/饮食/体测日志 | Postgres | Agent 引导前端录入 |
| 食物 / 动作 | Postgres | ~373 食物；~1324 动作 |
| 知识 chunks | Qdrant + BM25 文件 | `ingest --reset` 可重建 |
| Agent 任务与事件 | Postgres + 进程 SSE 缓冲 | 事件持久化；SSE 同进程 |
| LangGraph 检查点 | Postgres `lg_*` | 断点续跑 |
| 评估运行记录 | Postgres `evaluation_*` | `eval-all --persist` |
| Trace | 进程内存 deque(200) | 调试用途 |

### 6.2 Alembic 迁移（0001–0007）

| 迁移 | 内容 |
|------|------|
| `0001_initial` | users, profiles, food_items, plans + versions, logs, body_metrics, agent_tasks, audit_logs |
| `0002_exercises` | exercises 表；workout_logs.exercise_id |
| `0003_foods_source` | food_items.source / external_id / name_en |
| `0004_agent_persistence` | agent_tasks 扩展字段；agent_task_events/steps/tool_calls/checkpoints |
| `0005_engineering_p1` | users.role；refresh_tokens；data_sources；plan_adjustments |
| `0006_langgraph_checkpoint` | lg_checkpoints / lg_channel_blobs / lg_checkpoint_writes |
| `0007_evaluation_persistence` | evaluation_runs / evaluation_results / evaluation_cases |

```powershell
# 升级到最新 schema（每次拉代码后建议执行）
cd D:\FitPilot\backend
uv run python main.py migrate
```

### 6.3 统一响应格式

```json
{ "status": "ok", "request_id": "req_...", "data": { ... } }
{ "status": "error", "request_id": "req_...", "error": { "code": "...", "message": "..." } }
```

---

## 7. RAG 知识问答

### 7.1 流程

**RAG = 检索 + 生成**：召回证据 → `build_context` → Ollama 依据证据回答并挂 `citation`。

```text
磁盘文件 → parsing/* → chunking.py (~900字/重叠120)
         → embed → Qdrant upsert → BM25 rebuild
query → dense + BM25 → RRF(k=60) → Rerank → build_context → Ollama
```

- **幂等**：按 `document_id` 先删后写
- **拒答**：证据过少 → `no_answer=true`，不调用 LLM 胡编

### 7.2 支持格式

| 分组 | 后缀 | 模块 |
|------|------|------|
| 文本 | md, txt, rst, log | `parsing/text_plain.py` |
| Office | docx, pptx, xlsx | `parsing/office.py` |
| PDF | pdf | `parsing/pdf_parser.py` |
| Web | html, xml | `parsing/web.py` |
| 数据 | csv, tsv, json, jsonl | `parsing/data_tabular.py` |
| 图片 | png, jpg, webp… | `parsing/image_parser.py`（可选 OCR） |

完整说明：[`docs/INGEST_FORMATS.md`](docs/INGEST_FORMATS.md)。

---

## 8. LangGraph Agent

实现：`backend/app/graphs/fitness_graph.py`；状态：`graphs/state.py`。

### 8.1 意图分类

| 意图 | 示例 | 节点 |
|------|------|------|
| `risk_or_medical` | 胸痛、骨折、处方 | **safety**（阻断） |
| `plan_create` / `plan_adjust` | 生成/调整计划 | **plan_preview** → **plan_confirm** |
| `personal_data_query` | 我的档案、本周训练 | **personal** |
| `workout_log_write` / `diet_log_write` | 打卡引导 | **log_hint** |
| `small_talk` | 你好 | **boundary** |
| `knowledge_query`（默认） | 蛋白、减脂 | **rag** |

### 8.2 状态图（含 interrupt）

```text
classify ──► safety | boundary | rag | personal | log_hint
                │
plan ──► plan_preview ──► plan_confirm ──interrupt()──► plan_commit | plan_reject ──► END
```

| 节点 | 行为 |
|------|------|
| plan_preview | `preview_and_stage_plans`；`requires_confirmation=true` |
| plan_confirm | `interrupt()` 等待人工；SSE `approval_required` |
| plan_commit | `commit_plans` 写库 |
| plan_reject | 丢弃 pending，返回说明 |

### 8.3 任务 API 与 SSE

| 接口 | 说明 |
|------|------|
| `POST /agent/chat` | 同步一轮 |
| `POST /agent/tasks` | 异步；支持 `Idempotency-Key` |
| `GET /agent/tasks/{id}` | 任务详情 |
| `GET /agent/tasks/{id}/stream` | SSE（约 3 分钟） |
| `POST /agent/tasks/{id}/approve` | interrupt 恢复：`{"approve": true/false}` |
| `POST /agent/tasks/{id}/resume` | Checkpointer 断点续跑 |
| `GET /agent/tasks/{id}/checkpoint` | 检查点信息 |
| `GET /agent/traces` | 本地 Trace 列表 |

SSE 事件：`task_started`、`node_started`、`completed`、`approval_required`、`failed`、`error` 等。

---

## 9. 业务域工具与确定性计算

白名单：`backend/app/tools/domain.py`（**禁止** LLM 直接写库或算热量）。

| 工具 | 作用 |
|------|------|
| `check_risk` | 高风险词检测 |
| `get_user_profile_data` | 档案 + TDEE/宏量 |
| `recent_logs` | 近 7 天训练/饮食汇总 |
| `query_foods` | 食物库查询 |
| `preview_and_stage_plans` | 训练+饮食预览 |
| `commit_plans` / `rollback_plan` | 确认写入 / 回滚 |
| `weekly_adjust_preview` | 周联合调整诊断+预览 |
| `swap_meal_item` | 单餐换菜重优化 |
| `weekly_volume` | 训练容量（`training_load.py`） |

**营养**：`services/nutrition.py` — Mifflin-St Jeor TDEE、宏量分配。  
**食谱优化**：`services/meal_optimizer.py` — OR-Tools SCIP；`MEAL_USE_ORTOOLS=false` 时纯贪心。

---

## 10. 安全、合规与输入防护

| 措施 | 实现 |
|------|------|
| 产品边界 | 健身饮食辅助；**不提供**诊断/治疗 |
| 高风险拦截 | `safety` 节点 + `block_plan_upgrade` |
| 计划写库 | 必须用户 **approve**；Agent 仅 stage |
| 热量/宏量 | 食物库 per_100g × 克数，代码计算 |
| Prompt Injection | `InputSanitizer`；`UNSAFE_INPUT` 400 |
| Token 熔断 | 超预算 50% → 429 |
| JWT + Refresh | 生产更换 `JWT_SECRET`；`REFRESH_TOKEN_EXPIRE_DAYS` |
| RBAC | 知识入库、评估 API 需 `admin` |
| CORS | 开发 `*`；生产应收紧 |

---

## 11. 可观测性、Trace 与 Token 预算

| 能力 | 位置 |
|------|------|
| HTTP 指标 | `/metrics` |
| RAG / LLM 指标 | `fitpilot_retrieval_*`、`fitpilot_llm_*` |
| Token 快照 | `GET /metrics/tokens` |
| Trace | `GET /agent/traces`、`/agent/traces/{id}` |
| 就绪探测 | `GET /health/ready`（Postgres/Redis/Qdrant/Ollama/GPU） |
| CLI | `fitpilot status` / `status --local` |
| 生产监控 | Prometheus `:9090`、Grafana `:3000`（prod compose） |

---

## 12. 知识库与数据导入管线

### 12.1 语料目录

见 [`knowledge_base/SOURCES.md`](knowledge_base/SOURCES.md)。

### 12.2 导入命令（完整顺序）

```powershell
cd D:\FitPilot\backend

# 1. 确保 schema 最新
uv run python main.py migrate

# 2. 动作库 → Postgres（可选写入 Qdrant）
uv run python main.py seed-exercises
# uv run python main.py seed-exercises --to-qdrant --limit 100

# 3. 食物库（默认先 prepare_fdc_kb）
uv run python main.py seed-foods
# uv run python main.py seed-foods --no-prepare

# 4. 知识库 → Qdrant + BM25
uv run python main.py ingest
# 换语料 / 换 Embedding 模型时重建向量库（不动 Postgres 用户数据）：
uv run python main.py ingest --reset
# 指定目录：
uv run python main.py ingest --path D:\FitPilot\knowledge_base\raw\curated
```

### 12.3 清库原则

| 库 | 清理 | 场景 |
|----|------|------|
| Postgres 业务 | **否** | 账号、计划、打卡 |
| Qdrant | **是**（`ingest --reset`） | 换语料 / Embedding |
| BM25 索引 | 随 `--reset` | 自动重建 |

### 12.4 API 入库（需 admin Token）

- `GET /knowledge/formats`、`GET /knowledge/status`
- `POST /knowledge/ingest`、`/ingest/text`、`/ingest/upload`
- `POST /knowledge/search`（调试检索）
- `POST /knowledge/collections/ensure`

---

## 13. 外部数据集与参考项目

目录：`例子或数据/` — 详见 [`例子或数据/README.md`](例子或数据/README.md)。

| 路径 | 用途 |
|------|------|
| `workout-cool-main/` | 产品理念参考 |
| `exercises-dataset-main/` | 动作库 JSON |
| `FoodData_Central_*中文翻译包/` | `prepare_fdc_kb.py` |
| `FoodData_Central_foundation_food_json_*.json` | USDA 英文回退 |

---

## 14. 环境变量与配置

```powershell
cd D:\FitPilot
Copy-Item .env.example .env
# 编辑 .env：JWT_SECRET、模型路径、设备选型等
```

| 分类 | 变量 | 说明 |
|------|------|------|
| 应用 | `APP_ENV`, `APP_PORT`, `APP_DEBUG` | development / 8000 |
| JWT | `JWT_SECRET`, `JWT_EXPIRE_MINUTES` | 生产必改 |
| Refresh | `REFRESH_TOKEN_EXPIRE_DAYS` | 默认 14 天 |
| Worker | `AGENT_USE_WORKER` | `true` 时 API 入队 Redis |
| 食谱 | `MEAL_USE_ORTOOLS` | `true` 启用 SCIP |
| Postgres | `DATABASE_URL` | asyncpg 连接串 |
| Redis | `REDIS_URL` | |
| Qdrant | `QDRANT_URL`, `QDRANT_COLLECTION` | 6333 / fitpilot_knowledge |
| Ollama | `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_MODEL_RAG`, `OLLAMA_MODEL_JUDGE`, `OLLAMA_KEEP_ALIVE` | 按环节分模型，见下表 |
| Ollama 可选 | `OLLAMA_MODEL_REWRITE`, `OLLAMA_MODEL_CLASSIFY`, `OLLAMA_USE_LLM_*` | 默认关 LLM 改写/分类 |
| RAG | `EMBEDDING_*`, `RERANKER_*`, `RAG_TOP_K`, `RAG_SKIP_RERANK` | Embedding 建议 `cpu` 错峰 |
| 离线 | `RAG_OFFLINE=1` | 哈希向量 + BM25 |
| 入库截断 | `RAG_PDF_MAX_PAGES`, `RAG_CSV_MAX_ROWS`, `RAG_ENABLE_OCR`… | 见 INGEST_FORMATS |
| Token | `TOKEN_BUDGET`, `TOKEN_STOP_RATIO` | 100k / 50% 熔断 |
| 可观测 | `LOG_LEVEL`, `LANGFUSE_*` | 可选 Langfuse |
| HF | `HF_ENDPOINT` | 如 https://hf-mirror.com |

完整模板：`.env.example`。代码：`backend/app/core/config.py`。

前端：`frontend/.env` → `VITE_API_BASE=http://127.0.0.1:8000/api/v1`

**质量优先（显存允许）** 时可将 RAG 升到 4B，并保持 Embedding 在 CPU：

```env
OLLAMA_MODEL_RAG=qwen3.5:4b
EMBEDDING_DEVICE=cpu
OLLAMA_KEEP_ALIVE=30s
```

---

## 15. 从零部署（完整命令步骤）

以下按 **推荐顺序** 列出从零到可验收的全部命令。

### 15.1 前置依赖

| 依赖 | 版本建议 | 用途 |
|------|----------|------|
| Python | 3.11+ | 后端 |
| uv | 最新 | Python 包管理 |
| Node.js + pnpm | LTS | 前端 |
| Docker Desktop | 最新 | Postgres + Redis |
| Ollama | 最新 | 本地 LLM |
| Qdrant | Docker 或本机 | 向量库 |

```powershell
# 可选：检查环境
cd D:\FitPilot
$env:PYTHONPATH = "D:\FitPilot\backend"
$env:NO_PROXY = "127.0.0.1,localhost"
```

### 15.2 克隆与配置

```powershell
cd D:\FitPilot
Copy-Item .env.example .env
# 编辑 .env：确认 DATABASE_URL、QDRANT_URL、OLLAMA_MODEL 等
```

### 15.3 拉取 LLM 与模型权重

```powershell
ollama pull qwen2.5:0.5b
ollama pull qwen2.5:1.5b
# 可选质量优先：ollama pull qwen3.5:4b
# Embedding / Reranker 见 docs/MODEL_DOWNLOAD.md
# 或开发期设 RAG_OFFLINE=1 跳过 GPU 权重
```

### 15.4 启动基础设施

```powershell
cd D:\FitPilot
docker compose -f docker-compose.dev.yml up -d
docker ps
# 确认 fitpilot-postgres、fitpilot-redis 为 healthy
# Qdrant：使用本机已有容器，或取消 compose.dev 内 qdrant 注释后 up -d
```

### 15.5 安装后端依赖

```powershell
cd D:\FitPilot\backend
uv sync
```

### 15.6 数据库迁移

```powershell
uv run python main.py migrate
# 等价：uv run fitpilot migrate
# 根目录：cd D:\FitPilot && python main.py migrate
```

### 15.7 灌库（动作 + 食物 + 知识）

```powershell
uv run python main.py seed-exercises
uv run python main.py seed-foods
uv run python main.py ingest
```

### 15.8 安装前端依赖

```powershell
cd D:\FitPilot\frontend
pnpm install
```

### 15.9 启动服务（开发双终端）

```powershell
# 终端 1 — 后端 API
cd D:\FitPilot
python main.py api
# 或：cd backend && uv run python main.py api --reload

# 终端 2 — 前端
cd D:\FitPilot
python main.py web
# 或：cd frontend && pnpm start
```

| 服务 | URL |
|------|-----|
| 前端 | http://127.0.0.1:5173 |
| Swagger | http://127.0.0.1:8000/docs |
| API（推荐） | http://127.0.0.1:8000/api/v1 |
| 指标 | http://127.0.0.1:8000/metrics |
| 就绪 | http://127.0.0.1:8000/api/v1/health/ready |

### 15.10 验收命令

```powershell
cd D:\FitPilot\backend

# 依赖就绪（可不启 API）
uv run python main.py status --local

# 或通过 HTTP（需 API 已启动）
uv run python main.py status --base-url http://127.0.0.1:8000

# 单元测试（37+ 项）
uv run python main.py test
uv run python main.py test -v

# RAG 黄金集评估（需已 ingest）
uv run python main.py eval

# 七层全量评估
uv run python main.py eval-all

# 写入评估库 + LLM judge
uv run python main.py eval-all --persist --online
```

### 15.11 浏览器验收流程

1. 打开 http://127.0.0.1:5173 → **注册 / 登录**
2. **档案** 页填写身高体重、目标、器械
3. **对话** 页提问「减脂期每天吃多少蛋白」→ 观察 SSE 进度与引用
4. **对话** 页说「帮我生成一周训练和饮食计划」→ 出现确认 → **批准**
5. **计划** 页查看当前计划、Diff、回滚
6. **打卡** 页记录训练/饮食
7. **动作库 / 食物库** 浏览与 shuffle

---

## 16. Worker 异步任务模式

当 `AGENT_USE_WORKER=true` 时，API 将 Agent 任务入队 Redis，由独立 Worker 消费。

### 16.1 配置

```powershell
# .env
AGENT_USE_WORKER=true
REDIS_URL=redis://127.0.0.1:6379/0
```

### 16.2 启动（三进程）

```powershell
# 终端 1 — API
cd D:\FitPilot
python main.py api

# 终端 2 — Worker
cd D:\FitPilot
python main.py worker
# 或：cd backend && uv run python main.py worker --poll-timeout 5

# 终端 3 — 前端
python main.py web
```

生产 Compose 已内置 `worker` 服务（`docker-compose.prod.yml`）。

---

## 17. 生产环境部署

```powershell
cd D:\FitPilot

# 1. 配置生产 .env（JWT_SECRET、密码、CORS 等）
Copy-Item .env.example .env

# 2. 构建并启动全栈
docker compose -f docker-compose.prod.yml up -d --build

# 3. 容器内迁移与灌库（首次）
docker compose -f docker-compose.prod.yml exec backend python main.py migrate
docker compose -f docker-compose.prod.yml exec backend python main.py seed-exercises
docker compose -f docker-compose.prod.yml exec backend python main.py seed-foods
docker compose -f docker-compose.prod.yml exec backend python main.py ingest

# 4. 查看日志
docker compose -f docker-compose.prod.yml logs -f backend worker
```

| 服务 | 端口 | 说明 |
|------|------|------|
| backend | 8000 | FastAPI |
| worker | — | Agent 队列消费 |
| prometheus | 9090 | 指标采集 |
| grafana | 3000 | 默认密码 `fitpilot` |
| qdrant | 6333 | 向量库 |

> Ollama 默认通过 `host.docker.internal:11434` 连宿主机；请确保宿主机 Ollama 已启动且模型已 pull。

---

## 18. 备份与恢复

```powershell
cd D:\FitPilot\backend

# 备份 Postgres + BM25 索引到默认目录
uv run python main.py backup
# 指定输出目录
uv run python main.py backup --out D:\FitPilot\backups\2026-07-15

# 从备份恢复
uv run python main.py restore D:\FitPilot\backups\2026-07-15

# 根目录等价
cd D:\FitPilot
python main.py backup
python main.py restore D:\FitPilot\backups\2026-07-15
```

> Qdrant 向量库需单独备份 volume 或通过 `ingest` 重建。

---

## 19. CLI 命令大全

### 19.1 根目录 `python main.py`

```powershell
cd D:\FitPilot

# 前端
python main.py web          # Vite :5173
python main.py ui           # web 别名
python main.py dev          # web 别名

# 后端
python main.py api          # FastAPI :8000
python main.py api --port 8080 --no-reload

# 数据库
python main.py migrate

# 种子与入库
python main.py seed-exercises
python main.py seed-foods
python main.py ingest
python main.py ingest --reset

# Worker
python main.py worker

# 备份恢复
python main.py backup
python main.py restore <备份目录>

# 评估
python main.py eval
python main.py eval-all
python main.py eval-all --persist --online
python main.py eval-no-answer
python main.py eval-agent

# 运维
python main.py status --local
python main.py status --base-url http://127.0.0.1:8000
python main.py test
python main.py test tests/test_rag_basic.py -v

python main.py --help
```

### 19.2 后端 `fitpilot` / `uv run python main.py`

| 命令 | 作用 | 常用参数 |
|------|------|----------|
| **`api`** | 启动 FastAPI | `--host` `--port` `--reload` |
| `web` | **已废弃**（请用 `api`） | |
| `migrate` | `alembic upgrade head` | |
| `worker` | Agent Worker | `--poll-timeout` |
| `backup` | 备份 | `--out` |
| `restore` | 恢复 | `<备份目录>` |
| `seed-exercises` | 动作库 | `--to-qdrant` `--limit` |
| `seed-foods` | 食物库 | `--no-prepare` |
| `ingest` | 知识入库 | `--reset` `--path` |
| `eval` | RAG 评估 | `--suite` `--top-k` `--out` `--config` |
| `eval-all` | 七层评估 | `--config` `--out` `--md` `--persist` `--online` |
| `eval-no-answer` | 拒答评估 | `--suite` |
| `eval-agent` | Agent 路由评估 | `--suite` |
| `status` | 依赖探测 | `--local` 或 `--base-url` |
| `test` | pytest | 透传 pytest 参数 |

```powershell
cd D:\FitPilot\backend
uv run fitpilot api
uv run python main.py eval --out ..\evals\reports\rag_$(Get-Date -Format yyyyMMdd).json
uv run python main.py eval-all --persist --online --out ..\evals\reports\full_eval.json
```

---

## 20. REST API 参考

> 前缀：**`/api/v1`**（根路径无版本前缀仍兼容）。  
> 除注册/登录/health 外，多数接口需 `Authorization: Bearer <access_token>`。

### 20.1 鉴权

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 注册 |
| POST | `/auth/login` | 登录，返回 access + refresh |
| POST | `/auth/refresh` | 刷新 access token |
| POST | `/auth/logout` | 吊销 refresh token |

```powershell
# 注册
Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8000/api/v1/auth/register `
  -ContentType "application/json" `
  -Body '{"email":"demo@fitpilot.local","password":"Demo1234!","display_name":"Demo"}'

# 登录
$r = Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8000/api/v1/auth/login `
  -ContentType "application/json" `
  -Body '{"email":"demo@fitpilot.local","password":"Demo1234!"}'
$token = $r.data.access_token
```

### 20.2 用户档案

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/users/me/profile` | 读取档案 |
| PUT | `/users/me/profile` | 更新档案 |

### 20.3 食物与动作

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/foods` | 列表/搜索 |
| POST | `/foods` | 新增食物 |
| GET | `/exercises` | 动作列表（query 筛选） |
| GET | `/exercises/facets` | 器械/部位聚合 |
| POST | `/exercises/shuffle` | 换一组动作 |
| GET | `/exercises/{id}` | 动作详情 |

### 20.4 打卡日志

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/workouts/logs` | 训练记录 |
| DELETE | `/workouts/logs/{id}` | 删除 |
| GET/POST | `/diet/logs` | 饮食记录 |
| GET/POST | `/body-metrics` | 体测记录 |

### 20.5 计划

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/plans/current` | 当前生效计划 |
| POST | `/plans/preview` | 预览（不经 Agent） |
| POST | `/plans/{id}/approve` | 确认写入（支持 pending 字段） |
| POST | `/plans/{id}/rollback` | 回滚版本 |
| POST | `/plans/weekly-adjust` | 周联合调整预览 |
| POST | `/plans/meals/swap` | 单餐换菜重优化 |

`POST /plans/meals/swap` 请求体示例：

```json
{
  "diet_plan_id": 1,
  "day_index": 0,
  "meal_index": 1,
  "exclude_food_ids": [12, 34]
}
```

### 20.6 Agent

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/agent/chat` | 同步对话 |
| POST | `/agent/tasks` | 创建异步任务 |
| GET | `/agent/tasks/{id}` | 任务状态 |
| GET | `/agent/tasks/{id}/stream` | SSE |
| POST | `/agent/tasks/{id}/approve` | `{"approve": true, "comment": "..."}` |
| POST | `/agent/tasks/{id}/resume` | Checkpointer 续跑 |
| GET | `/agent/tasks/{id}/checkpoint` | 检查点 |
| GET | `/agent/traces` | Trace 列表 |
| GET | `/agent/traces/{id}` | Trace 详情 |

### 20.7 知识库（入库需 admin）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/knowledge/formats` | 支持格式 |
| GET | `/knowledge/status` | 向量库状态 |
| POST | `/knowledge/collections/ensure` | 确保集合 |
| POST | `/knowledge/ingest` | 目录入库 |
| POST | `/knowledge/ingest/text` | 内联文本 |
| POST | `/knowledge/ingest/upload` | 上传文件 |
| POST | `/knowledge/search` | 调试检索 |

### 20.8 评估（admin）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/eval/runs` | 评估运行列表 |
| GET | `/eval/runs/{id}` | 单次运行详情 |

### 20.9 健康与指标

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 存活 |
| GET | `/health/ready` | 全依赖就绪 |
| GET | `/metrics` | Prometheus |
| GET | `/metrics/tokens` | Token 用量 |

---

## 21. 前端页面与交互

路由：`frontend/src/router/index.ts`

| 路径 | 页面 | 功能 |
|------|------|------|
| `/login` | LoginView | 注册/登录 |
| `/` | DashboardView | 仪表盘 |
| `/profile` | ProfileView | 档案编辑 |
| `/logs` | LogsView | 训练/饮食/体测打卡 |
| `/foods` | FoodsView | 食物库 |
| `/exercises` | ExercisesView | 动作库、shuffle |
| `/chat` | ChatView | Agent 对话 + SSE + 计划批准 |
| `/plans` | PlansView | 计划预览、Diff、确认、回滚 |

**状态管理**：

- `stores/auth.ts`：JWT + Refresh Token 持久化；401 自动 refresh
- `stores/chat.ts`：SSE 订阅；`approval_required` 时优先 `POST /agent/tasks/{id}/approve`

**构建与预览**：

```powershell
cd D:\FitPilot\frontend
pnpm install
pnpm start          # 开发
pnpm build          # 生产构建
pnpm preview        # 预览 dist
```

---

## 22. 测试、七层评估与 CI

### 22.1 单元测试

```powershell
cd D:\FitPilot\backend
uv run python main.py test
uv run python main.py test -v
uv run python main.py test tests/test_meal_optimizer.py -v
```

覆盖：BM25/切分、解析器、Agent 路由、营养、Token、消毒、计划硬约束、食谱优化、Checkpointer 等。

### 22.2 RAG 单层评估

```powershell
uv run python main.py eval
uv run python main.py eval --suite ..\evals\golden_rag.json --top-k 4 `
  --out ..\evals\reports\last.json --config ..\evals\eval_config.json
```

指标：`hit_rate`、`hit@K`、`mrr`、`citation_rate`、`avg_latency_ms`。

### 22.3 多层评估（eval-all，9 模块）

配置：[`evals/eval_config.json`](evals/eval_config.json)（与 `eval_config.yaml` 同步）。详解见 [`docs/EVAL.md`](docs/EVAL.md)。

| 层 | 模块 | 评测集 | 指标 |
|----|------|--------|------|
| 1 | parsing | `parsing_cases.json` | 解析成功率（txt/md/csv/json/html…） |
| 2 | retrieval | `golden_rag.json`（≥20 条） | Hit@K / MRR |
| 2b | no_answer | `no_answer_cases.json`（正负样本） | Recall / Precision |
| 3 | generation | `generation_cases.json` | 静态引用规则 + e2e 检索 |
| 3b | generation_online | `generation_online_cases.json` | LLM-as-judge（`--online`） |
| 4 | agent | `agent_routing_cases.json`（全意图） | 意图准确率 / F1 |
| 5 | plan | `plan_cases.json` | 训练硬约束 |
| 6 | meal | `meal_cases.json` | 宏量误差 / 忌口 |
| 7 | safety | `safety_cases.json` | 风险识别 / 周调整 |

```powershell
# 全量多层
uv run python main.py eval-all

# 指定输出
uv run python main.py eval-all --out ..\evals\reports\full_eval.json --md ..\evals\reports\full_eval.md

# 持久化到 evaluation_runs + 在线 judge
uv run python main.py eval-all --persist --online

# 分项
uv run python main.py eval-no-answer
uv run python main.py eval-agent
```

报告默认：`evals/reports/full_eval_latest.json` / `.md`。`--persist` 会写入各层 `cases` 明细。

### 22.4 CI

GitHub Actions：`.github/workflows/ci.yml` — push/PR 运行核心 pytest（不依赖外部 Ollama/Qdrant）。

---

## 23. 管理员与 RBAC

默认注册用户角色为 `user`。知识库入库与评估 API 需要 `admin`。

```powershell
# 将首个用户提升为 admin（在 Postgres 中执行）
docker exec -it fitpilot-postgres psql -U fitpilot -d fitpilot -c `
  "UPDATE users SET role='admin' WHERE id=1;"
```

`require_role("admin")` 用于：`/knowledge/ingest*`、`/eval/runs*`。

---

## 24. 性能与延迟优化

典型对话 **~1 分钟** 时，耗时多在 **Ollama 生成**。

| 手段 | 配置/操作 |
|------|-----------|
| 跳过精排 | `RAG_SKIP_RERANK=true` |
| 更小 LLM | 换 Ollama 模型 |
| 显存错峰 | `EMBEDDING_DEVICE=cpu` |
| 降低召回 | 调小 `RAG_TOP_K` / `RAG_RERANK_TOP_K` |
| 离线开发 | `RAG_OFFLINE=1` |
| Worker 解耦 | `AGENT_USE_WORKER=true` 避免 API 阻塞 |
| 食谱求解 | `MEAL_USE_ORTOOLS=false` 可略快但精度下降 |

---

## 25. 路线图与未实现项

| 阶段 | 状态 | 说明 |
|------|------|------|
| 阶段 1：业务基础 | ✅ | 鉴权、CRUD、Vue 全页面 |
| 阶段 2：RAG 基线 | ✅ | 多格式、混合检索、引用/拒答 |
| 阶段 3：Agent 闭环 | ✅ | LangGraph、SSE、计划确认 |
| 工程 P0 | ✅ | Agent 持久化、硬约束、Diff、`/api/v1` |
| 工程 P1 | ✅ | RBAC、Refresh、Worker、备份、周调整 |
| LangGraph Checkpointer | ✅ | interrupt + resume + Postgres 全状态 |
| OR-Tools 食谱 | ✅ | SCIP + 贪心回退 + meals/swap |
| 七层评估 | ✅ | eval-all + DB 持久化 + LLM judge |
| 生产 Compose | ✅ | backend + worker + Prometheus/Grafana |
| 前端 meals/swap UI | ⏳ | API 已就绪，PlansView 待接 |
| 评估看板前端 | ⏳ | `/eval/runs` API 已就绪 |
| Parent-Child 检索 | ⏳ | P2 |
| LLM 流式输出 | ⏳ | P2 |
| Langfuse 默认接入 | ⏳ | 配置项已有 |

---

## 26. 相关文档索引

| 文档 | 内容 |
|------|------|
| [`docs/MODEL_DOWNLOAD.md`](docs/MODEL_DOWNLOAD.md) | Embedding / Reranker / Ollama |
| [`docs/INGEST_FORMATS.md`](docs/INGEST_FORMATS.md) | 多格式解析与 OCR |
| [`docs/EVAL.md`](docs/EVAL.md) | RAG 评估详解 |
| [`docs/ENGINEERING_REVIEW.md`](docs/ENGINEERING_REVIEW.md) | 工程审查落地对照 |
| [`docs/MIGRATION_FROM_LLM_KB.md`](docs/MIGRATION_FROM_LLM_KB.md) | llm-kb 迁入能力 |
| [`knowledge_base/SOURCES.md`](knowledge_base/SOURCES.md) | 知识库出处与清库 |
| [`例子或数据/README.md`](例子或数据/README.md) | 外部数据集 |
| [`backend/README.md`](backend/README.md) | 后端短命令 |
| [`frontend/README.md`](frontend/README.md) | 前端短命令 |
| [`models/README.md`](models/README.md) | 本地模型目录 |
| `.env.example` | 全量环境变量 |

---

**FitPilot** — 结构化健身数据 + 可引用知识 + interrupt 可确认计划 + 七层可验收评估 + 可观测可运维的本地 AI Agent MVP。
