# FitPilot 工程化与 Agent/RAG 增强落地说明

对应文档：`FitPilot Engineering and Agent-RAG Enhancement Plan.docx`

配套：

- 架构图：[`ARCHITECTURE.md`](./ARCHITECTURE.md)
- 演示清单：[`DEMO.md`](./DEMO.md)

## 阶段一：可靠任务基础设施（P0）

Redis Streams / ACK / 死信、SSE 仅 Postgres、approve 幂等、CORS/JWT 生产加固。

## 阶段二：Agent Runtime（P1）

| 项 | 位置 |
|----|------|
| 结构化路由 + 子图 + PEV | `agents/` |
| Application create/approve/cancel/resume | `application/agent/` |
| Repository + UoW | `infrastructure/persistence/` |
| 受控记忆 | `agents/memory/` + `user_memories` / `session_memories` |
| **偏好确认写回档案** | `application/memories/confirm_memory.py`（`apply_to_profile`） |
| 统一审批载荷 | `agents/runtime/policies.build_approval_payload` |
| 记忆 API | `/memories` + confirm 写回 |

## 阶段三：RAG 服务（P1）

Evidence Gate / RetrievalPlan / 类型分块 / Citation / 增量入库 / 回滚 / Qdrant 快照。

## 阶段四：评估与 CI

- 离线：`fitpilot eval-gate`（主 CI）
- 在线可选：`.github/workflows/online-eval.yml`（需 secrets，失败不阻断）

## 阶段五：展示与演示

| 项 | 位置 |
|----|------|
| Agent 轨迹 / RAG 证据 / **审批 Diff 面板** | `frontend/src/views/ChatView.vue` |
| 一键演示数据 | `fitpilot seed-demo` |
| 架构图 / 演示清单 | `docs/ARCHITECTURE.md`、`docs/DEMO.md` |

## 验证

```bash
cd backend
uv run python main.py migrate
uv run python -m pytest -q \
  tests/test_enhancement_plan.py \
  tests/test_agent_runtime.py \
  tests/test_phase3_engineering.py \
  tests/test_rag_phase4.py \
  tests/test_memory_and_approval.py
uv run python main.py eval-gate
uv run python main.py seed-demo
```

## 方案收尾说明

增强方案中的 P0/P1 主干已落地。可选增强（非阻塞）：

- 自托管环境下配置 secrets 跑在线 RAG CI
- 录制演示视频
- 偏好确认后同步更多档案字段的产品化 UI
