# 工程审查改进落地对照



来源文档：[`FitPilot Engineering Review and Improvement Plan.docx`](../FitPilot%20Engineering%20Review%20and%20Improvement%20Plan.docx)  

文本提取：[`ENGINEERING_REVIEW_PLAN.txt`](ENGINEERING_REVIEW_PLAN.txt)



## P0 已落地



| 审查项 | 实现 |

|--------|------|

| CLI 语义：`web`=前端、`api`=后端 | 根目录 `main.py`、后端 `fitpilot api` |

| API 版本前缀 | `/api/v1/*`（根路径仍兼容） |

| Agent 任务/事件持久化 | 迁移 `0004` |

| SSE 可恢复 | `Last-Event-ID`、心跳、`GET /agent/tasks/{id}` |

| Planner–Executor | `complex_plan` 节点 |

| 训练计划硬约束 | `training_plan_validator.py` |

| 膳食忌口/热量下限 | `diet_plan_validator.py` |

| 计划修改 Diff | `plan_diff.py` |

| RAG 多信号拒答 | `context.py` |

| 上传安全 | `upload_security.py` |

| 路径去硬编码 | `Settings.project_root` |



## P1 已落地（本次）



| 审查项 | 实现 |

|--------|------|

| 独立 Worker + Redis 队列 | `app/worker/`、`fitpilot worker`、`AGENT_USE_WORKER` |

| LangGraph Checkpointer | `PostgresCheckpointSaver` → `agent_checkpoints` |

| 训练模板库 | `training_templates.py` |

| 渐进负荷规则 | `progressive_load.py` |

| 食谱贪心优化 | `meal_optimizer.py` |

| 周联合调整 | `weekly_adjustment.py`、`POST /plans/weekly-adjust` |

| Parent-Child 分块 | `parent_child.py`、`chunking.split_text_parent_child` |

| Query 改写 / Multi-Query | `query_understanding.py` → `hybrid_retrieve` |

| Refresh Token + RBAC | 迁移 `0005`、`/auth/refresh`、`require_role` |

| 备份/恢复 | `scripts/backup.py`、`scripts/restore.py`、`fitpilot backup` |

| 评估扩展 | `no_answer_eval.py`、`agent_eval.py`、`eval-no-answer`、`eval-agent` |

| 生产 Compose | `worker` + `prometheus` + `grafana` 服务 |

| 前端 PlansView | Diff 表格 + 周调整 + 预览折叠 |

| BM25 路径 | `get_settings().project_root` |



## 迁移



```powershell

cd D:\FitPilot\backend

uv run python main.py migrate   # 0004 + 0005

```



## CLI 速查



```powershell

# 仓库根目录

python main.py web    # 前端 :5173

python main.py api    # 后端 :8000



# backend 目录

uv run python main.py api

uv run python main.py worker          # Agent Worker

uv run python main.py eval-no-answer

uv run python main.py eval-agent

uv run python main.py backup

```



## 环境变量



| 变量 | 说明 |

|------|------|

| `AGENT_USE_WORKER=true` | Agent 任务入 Redis，由 worker 消费 |

| `JWT_EXPIRE_MINUTES=60` | 短效 Access Token |

| `REFRESH_TOKEN_EXPIRE_DAYS=14` | Refresh Token 有效期 |



## 本次收尾（接续会话）



| 项 | 状态 |

|----|------|

| `cli.py` 重复命令去重 | ✅ 已修复 |

| Worker 进度事件持久化（progress sink） | ✅ `agent_runner.py` |

| 前端 Refresh Token + 401 自动续期 | ✅ `auth.ts` + `api/client.ts` |

| PlansView Diff 对齐 `plan_diff.changes` | ✅ |

| 知识库入库 RBAC（admin） | ✅ `require_role("admin")` |

| `agent_runner` 模块入口 `__main__` | ✅ Docker `python -m app.worker.agent_runner` |

| `.env.example` Worker / Refresh 变量 | ✅ |

| 单测 | ✅ 32 passed |



## P2 推进（LangGraph 全状态 + OR-Tools + 七层评估）



| 项 | 实现 |

|----|------|

| LangGraph 全状态 Checkpointer | `lg_checkpoints` / `lg_channel_blobs` / `lg_checkpoint_writes` + `PostgresCheckpointSaver`（serde + `aput_writes` + 每步 commit） |

| 任务恢复 API | `GET /agent/tasks/{id}/checkpoint`、`POST /agent/tasks/{id}/resume` |

| OR-Tools 食谱优化 | `meal_optimizer.py` SCIP 约束求解，`MEAL_USE_ORTOOLS` |

| 七层评估 | `parsing/generation/plan/meal/safety_eval` + `full_eval.py` + `fitpilot eval-all` |

| 评测集 | `evals/parsing_cases.json` … `safety_cases.json`，`eval_config.json` 全模块 |

| 单测 | ✅ 36 passed |



## 深化项（本轮）



| 项 | 实现 |

|----|------|

| LangGraph `interrupt()` 计划确认 | `plan_preview` → `plan_confirm` → `plan_commit/reject` |

| Agent 批准恢复 | `POST /agent/tasks/{id}/approve` + `Command(resume=...)` |

| 前端对话批准 | `chat.ts` 优先走 Agent approve API |

| 评估 DB 持久化 | `evaluation_runs/results/cases` + `eval-all --persist` |

| 评估看板 API | `GET /api/v1/eval/runs`（admin） |

| LLM-as-judge | `generation_online_eval.py` + `eval-all --online` |

| 单餐换菜重优化 | `POST /plans/meals/swap` + `swap_meal_item()` |

| 单测 | ✅ 37 passed |

