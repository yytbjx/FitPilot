# FitPilot 项目全面审查与改进方案

> 审查范围：Agent 核心架构、RAG + 评估体系、基础设施/安全/仓库卫生（只读审查，未修改代码）
> 审查基准：分支 `main`，HEAD `88181d1`

---

## 一、总体结论

**FitPilot 不是玩具项目，但也还不是一个成熟的生产级 Agent 项目。** 准确评级是：**"功能完整的准生产级工程原型"**。

| 维度 | 评级 | 一句话总结 |
|---|---|---|
| Agent 架构 | 🟡 骨架优秀、执行层薄弱 | LangGraph 全状态 checkpoint + interrupt 审批 + SSE 断线续传选型到位；但无任务超时/取消、无 stale 任务收割、幂等只覆盖入口 |
| RAG 检索 | 🟡 链路完整、静默降级致命 | Dense+BM25→RRF→Rerank→Evidence Gate 全链路真实实现；但所有降级路径静默，模型一挂质量全毁且无告警 |
| 领域服务 | 🟢 项目最扎实的部分 | 营养计算（Mifflin-St Jeor）、配餐（OR-Tools MIP 真实求解）、训练计划校验全部为确定性规则引擎，不依赖 LLM 编造 |
| 数据库/迁移 | 🟢 成熟 | 单一 alembic 体系、9 个迁移链完整、索引设计良好 |
| 鉴权/安全主线 | 🟡 | refresh token 旋转 + RBAC + 上传校验达标；但登录零限流、密码策略弱、prod compose 硬编码弱凭据 |
| 部署闭环 | 🔴 半成品 | Dockerfile 必然构建失败（缺 uv.lock 复制）、prod compose 无前端服务、无迁移步骤、Grafana 空配置 |
| 仓库卫生 | 🔴 最差项 | 约 378 MB 第三方副本/数据集/生成索引被 git 跟踪 |
| 测试/CI | 🟡 | 16 个测试文件 CI 只跑 14 个；eval 门禁不覆盖 RAG 检索层；无 lint/前端 CI/Docker 构建验证 |
| 前端 | 🟡 真实 MVP | Vue 3 + Element Plus，8 个 view、401 自动刷新令牌写法接近生产级；但无测试、无生产打包链路 |
| 文档一致性 | 🟢 好得出乎意料 | docs/ 与代码高度吻合；仅 README 双份并存造成困惑 |

**核心判断：短板全部是 1–2 个迭代内可补齐的工程债，不是架构性问题。**

---

## 二、冗余部分清单（可安全删除/清理）

### 2.1 仓库级冗余（🔴 约 378 MB 被 git 跟踪）

| 路径 | 体积 | 处置 |
|---|---|---|
| `_refs/`（workout-cool 等第三方完整副本，含数百张图片） | ~179 MB | `git rm -r --cached` + .gitignore，需要时改 submodule 或只留数据链接 |
| `例子或数据/`（USDA 大 JSON、翻译包 zip、又一份 workout-cool 副本——与 `_refs` 重复） | ~200 MB | 移出 git，数据集放 release/外部存储 |
| `knowledge_base/bm25_index.json` | 4.9 MB | 本地生成物不应入库（同类 `index_versions.jsonl` 已被 ignore，规则不一致），加 ignore |
| `frontend/tsconfig.tsbuildinfo` | — | 构建缓存，删除 + ignore `*.tsbuildinfo` |
| `_enhancement_plan_extract.txt` | — | docx 提取中间产物，删除 |
| `_doc.zip` / `_doc_text.txt`（5 字节提取失败残留）/ `_doc_text_utf8.txt` / `_docx_extract/` / `FitPilot/`（GitHub Desktop 误建的嵌套空 .git 目录） | — | 已正确 ignore，删本地副本即可 |
| `eval_datasets/`（仅空 .gitkeep） | — | 真实评测集都在 `evals/`，删除目录 |
| `knowledge_base/processed/` | — | 空目录、无代码引用，删除 |
| `README.md` vs `README2.md` | — | 内容大面积重叠，合并为一，旧版归档到 `docs/archive/` |
| `项目README全量归档生成提示词.md` | — | 个人工作流残留，移出仓库 |
| 根目录 3 个 `.docx` 设计文档 | — | 移入 `docs/` |

### 2.2 代码级冗余 / 死代码

| 项 | 位置 | 判定 |
|---|---|---|
| `parsers.py` | `backend/app/rag/parsers.py` | 纯转发 shim 且全仓无 import 方，常量与 registry 可能漂移，**删除** |
| `evaluation/` 包 | `backend/app/evaluation/__init__.py` | 只有一行 docstring 的空壳占位，**删除**（真实评估在 `eval/`） |
| `AgentCheckpoint` 表 + `save_checkpoint` | `services/agent_persistence.py:153` | 与 LangGraph `PostgresCheckpointSaver` **双检查点并存**，resume 完全不读它，纯冗余写入，**删除自研那套** |
| `legacy_simple_preview` | `agents/workflows/plan_workflow.py:146` | 无任何调用方 |
| `LEGACY_QUEUE_KEY` | `worker/redis_queue.py:27` | 仅声明从未读写 |
| `upsert_task_step` / `record_tool_call` | `services/agent_persistence.py:94,130` | 无调用方，对应审计表 `AgentTaskStep`/`AgentToolCall` 永远为空——要么接线要么删表 |
| planner 知识路径步骤 | `agents/runtime/planner.py:38-43` | 生成的知识检索步骤在 executor 中只返回 `{"delegated": True}`，永远不会产生真实效果 |
| registry 的 `handler`/`input_schema`/`timeout_seconds` | `tools/registry.py:31,34` | executor 是硬编码 if-elif 链，从不读这三个字段，声明空转 |
| 三处"复杂任务"判定 | `routing.py` / `fitness_graph.py:130` / `planner.py:50` | 三套正则各写各的，规则漂移只是时间问题 |
| 根 `main.py:74` | — | `cmd == "web"` 在第 66 行已退出，第 74 行是死代码 |
| `deploy/prometheus.yml` vs `monitoring/prometheus/prometheus.yml` | — | 两份配置 target 不同已漂移，合一 |
| `evals/eval_config.json` vs `eval_config.yaml` | — | 双格式并存，保留一种 |
| `models/bge-reranker-large/` 中 `model.safetensors` + `pytorch_model.bin` | 各 2.24 GB | 只用一个，**约 4.5 GB 重复权重**（不入库但占磁盘） |
| `qdrant_client.py:34` 的 `httpx.Client` | — | 创建后从未使用的死属性 |
| 12 个 eval 模块的结构性重复 | `rag_eval`/`no_answer_eval`/`generation_eval` 同一流程写三遍；Result dataclass 模板在 5 个文件逐字重复 | 抽公共基类 |
| `app/main.py:69,71` 双路由挂载 | — | `/api/v1` 前缀 + 无前缀双份路由表，保留前缀版即可 |

### 2.3 半死不活的"虚化框架"（需决策而非直接删）

**Planner/Executor/Validator + 工具 Registry 框架声明式空转**：planner 产出的 plan 被 workflow 整体改写（`plan_workflow.py:27-33,67-71`）；executor 的"自动修复"`continue` 会跳过失败步骤，重试语义是错的（`executor.py:93-107`）；registry 元数据无人消费。**必须在"让声明式真正驱动执行"与"删掉简化成函数调用"之间二选一**，维持现状是最差选项。

---

## 三、严重问题清单（按修复优先级）

### P0 — 可靠性闭环缺失（Agent 执行层）

1. **S1 无任务超时/真实取消**：worker 对图执行无 `asyncio.wait_for`；`cancel_agent_task` 只改 DB 状态，正在跑的图继续执行并可能覆盖 `cancelled` 状态（`agent_persistence.py:83` 无条件覆盖 status）。
2. **S5 任务可永久卡在 `queued`**：入队 fire-and-forget（`agent_runner_service.py:144`），进程崩溃即丢，**无 stale 任务 reaper**；默认进程内模式重启丢全部在途任务。
3. **S6 执行层不幂等**：worker 重试从 checkpoint 重跑整个图，`preview_and_stage_plans`（注册时自标 `idempotent=False`）会产生多份草稿计划。
4. **S2 pending_actions 残留脏数据**：commit/reject 后 DB 里旧 pending 永远清不掉，`GET /tasks/{id}` 一直返回过期计划（`agent_persistence.py:87` 条件 bug）。**一天内可修**。
5. **S4 SessionMemory 无唯一约束**：并发写可插入重复行且读写命中不同行（`models/memory.py:34-48`）。**一天内可修**（加 `(user_id, session_id)` UniqueConstraint + upsert）。

### P0 — RAG 静默降级（质量崩溃不可观测）

6. **Embedding 哈希回退**：模型加载失败回退为 SHA256 哈希向量（`embeddings.py:41-66`），检索质量全毁但照常运行，还污染评估指标。应改为**硬失败 + 健康检查暴露**。
7. **Reranker 失败→全站拒答**：失败返回 0 分（`rerank.py:44-46`）恰好触发 LOW_CONFIDENCE 拒答逻辑（`context.py:48-56`），且无指标区分"模型故障"与"知识缺失"。
8. **`retrieve_with_plan` 全局配置突变**：通过 `object.__setattr__` 改全局 settings（`retrieval_plan.py:92-103`），FastAPI 并发下**高风险查询可能以其他请求的低配参数执行，跳过 rerank**。真实并发 bug，改参数传递。

### P0 — 安全运营面

9. **prod compose 硬编码弱凭据**：`POSTGRES_PASSWORD: fitpilot`、`GF_SECURITY_ADMIN_PASSWORD: fitpilot`、Redis/Qdrant 无认证无 TLS——按此文件部署即被接管。
10. **登录/注册零限流**：全仓无限流实现，`/auth/login` 可无限爆破；配合密码 `min_length=6` 无复杂度要求（`schemas/auth_biz.py`）。

### P0 — 部署闭环断裂

11. **Dockerfile 必然构建失败**：未 COPY `uv.lock`，`uv sync` 失败后落到 `|| uv pip install --system -e .` 兜底——依赖未锁定、构建不可复现，且装到 system python 却 PATH 指向 .venv，前后矛盾。
12. **prod compose 跑不出完整系统**：无 frontend 服务、无 alembic 迁移步骤、worker 无 healthcheck、Grafana 零 provisioning（空目录）。

---

## 四、中等问题（择要）

- **M4 Token 预算是进程级全局单例**：一个用户打满预算，全站 429（`token_monitor.py:174-185`）→ 改每用户/每任务维度。
- **M1 检查点/事件/记忆表全部无界增长**：`adelete_thread` 从未被调用，无 TTL/归档策略。
- **M2 worker 重试不区分错误类型**：bug 类错误固定重试 3 次且 checkpoint 断点续跑语义混乱；退避 sleep 阻塞队列头（单 worker 时最长 60s）。
- **M7 事件 seq 用 `max(seq)+1` 无唯一约束**，SSE 断线续传依赖 seq 单调，并发下会撞号。
- **M12 approve/cancel 无行锁**（全仓无 `with_for_update`），并发覆盖。
- **M3 SSE 硬上限 ~180 秒**，长任务客户端静默断流。
- **同步模型调用阻塞事件循环**：`model.encode`/`CrossEncoder.predict` 在 async 路径直接执行（`retrieve.py:41,210`），并发吞吐杀手 → `asyncio.to_thread`。
- **证据门双套启发式并存**：`assess_evidence` 与 `build_context` 判定条件不一致，RRF 分（0.01 量级）传入按 CrossEncoder 原始分（阈值 5）设计的冲突检测——该分支永不触发。
- **embedding 维度硬编码 512**（`embeddings.py:73`、`ingest.py:51`）；`CHUNKER_VERSION` 不随分块策略变化——换模型/改策略不会触发索引失效。
- **知识库删除生命周期缺失**：无 delete API、`diff_knowledge_dir` 不识别 deleted、rollback 无法恢复已删文件。
- **CI 门禁不覆盖 RAG 检索层**：`OFFLINE_LAYERS` 只有 5 层，retrieval/no_answer/generation 无防线；`online-eval.yml` `continue-on-error: true` 永不 fail。
- **JWT 默认 `change-me`、CORS `*` + credentials、`APP_DEBUG` 默认 True 驱动 SQL echo**——均有生产校验但依赖部署者记得设 `APP_ENV=production`。
- **`/knowledge/ingest` 接受任意绝对路径**，admin 令牌泄露即任意文件读取 → 白名单目录。
- **版本表缺 `(plan_id, version)` 联合唯一约束**，并发写版本号可撞车。
- **UserMemory 提议无去重无上限**，慢速无界增长。

---

## 五、改进方案（按迭代组织）

### 迭代 1（本周，低成本高收益）

1. 修 S2：commit/reject 后显式清空 DB `pending_actions`。
2. 修 S4：`SessionMemory` 加 `(user_id, session_id)` 唯一约束 + 改 upsert；补迁移 0010。
3. 仓库大扫除：执行 §2.1 清理清单（`git rm -r --cached _refs/ "例子或数据/" knowledge_base/bm25_index.json frontend/tsconfig.tsbuildinfo`），补 .gitignore，合并 README。
4. 删死代码：`parsers.py`、`evaluation/`、`eval_datasets/`、`AgentCheckpoint` 自研检查点、§2.2 全表。
5. `retrieve_with_plan` 改参数传递，消除全局 settings 突变（P0#8）。
6. Embedding 哈希回退改硬失败，embedding/reranker 健康纳入 `/health`。
7. CI 补跑 `test_engineering_p1.py`、`test_p2_features.py`；加 ruff。
8. prod compose 密钥全部外部化（env 注入，禁止默认值）。

### 迭代 2（可靠性闭环）

9. 任务级超时：`asyncio.wait_for` 包裹图执行；取消改协作式（图节点检查 cancel 标志）。
10. Stale 任务 reaper：定时扫描 `queued`/`running` 超时任务，标记失败并释放。
11. 幂等执行：`preview_and_stage_plans` 加任务级去重键；事件表加 `(task_id, seq)` 唯一约束；approve/cancel 加 `SELECT ... FOR UPDATE`。
12. Token 预算改每用户维度 + 每用户并发任务数上限。
13. Checkpoint/事件/记忆表 TTL 清理任务。
14. 修 Dockerfile（COPY uv.lock、删兜底、非 root 用户、HEALTHCHECK）；prod compose 补 frontend 服务 + 迁移 init 容器 + worker healthcheck；Grafana provisioning 落地；prometheus 配置合一。
15. 登录/注册限流（slowapi），密码策略提到 min_length=10 + 复杂度；`ingest` 路径白名单。

### 迭代 3（RAG 质量与框架决策）

16. embedding/rerank 调用移 `asyncio.to_thread`；模型懒加载加锁；删重复 pytorch_model.bin；`describe_rag_stack` 修正（声称 base 实际 large）。
17. 知识库生命周期闭环：delete 传播 + API 化、deleted diff、BM25/Qdrant 一致性校验、bm25 索引移出 git。
18. Evidence Gate 合并为单套判定；embedding 维度/分块版本纳入索引版本号，换模型自动失效。
19. 评估防线：retrieval/no_answer 纳入 CI 门禁（离线快照模式）、golden 集扩到百级、引入 nDCG、消除 yaml/json 双配置、抽 eval 公共基类。
20. **PEV 框架决策**：要么让 planner/registry 的声明真正驱动 executor（handler 调度、schema 校验、timeout 生效），要么删掉框架改直接函数调用——推荐后者（当前业务复杂度用不上）。
21. 前端：补 Dockerfile + `.env.production` 范例 + vue-tsc 入 CI + 基础组件测试。

---

## 六、最终判断：离"成熟"还差什么

**已经具备的（超过多数同类项目）**：LangGraph 全状态 checkpoint + interrupt 人机审批 + SSE 断线续传；Redis Streams 消费组 + 死信；refresh token 旋转 + RBAC；真实 MIP 配餐求解器；9 层评估体系雏形；规范 alembic 迁移链；文档与代码高度一致。

**距离成熟生产级的关键差距（按权重排序）**：
1. 可靠性闭环（超时/取消/reaper/幂等/TTL）——长跑系统必然劣化，**这是"原型"与"产品"的分水岭**；
2. 降级路径可观测性——所有"安静坏掉"的路径必须有指标和告警；
3. 部署闭环——prod 栈必须真能一键跑起来；
4. 安全运营面——限流、密钥管理、多租户资源隔离；
5. 框架去虚——删掉或真正启用声明式 PEV 框架。

完成迭代 1+2 后，可自评"Beta 生产可用"；完成迭代 3 后，达到成熟生产级 Agent 项目标准。
