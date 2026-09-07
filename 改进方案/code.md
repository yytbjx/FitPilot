# FitPilot Agent 系统优化改进方案（v2.0 · 2026-09-07）

**文档编号：** FP-OPT-2026-002
**适用项目：** https://github.com/yytbjx/FitPilot
**版本：** v2.0（评审稿）
**对齐基准：** Letta/MemGPT 分层记忆、Pliops 组合式 KV 复用、Anthropic Planner-Executor / Microsoft Magentic 多 Agent 编排、RULER v2 / LongBench v2 / NoLiMa 长上下文评测、MCP（Model Context Protocol）
**与现有工程对齐：** LangGraph 主图 + 五条领域子图、PostgresCheckpointSaver、`evals/eval_config.yaml` 多层门禁、规则三级意图路由、Redis Streams 异步 Worker。

---

## 0. 摘要与核心增量

在保持 FitPilot 现有 LangGraph 编排、确定性领域引擎、RAG Evidence Gate、人机审批与全链路持久化能力不变的前提下，本方案聚焦三个工程模块的升级与一项评测体系的扩容：

1. **分层记忆（升级）**：在现有"会话摘要 + 用户偏好候选"基础上，引入 Letta/MemGPT 风格的 **Core / Recall / Archival** 三层，持久化层由 `conversation_memory` 表 + `pgvector` 索引承担，原始消息全程可回溯<span data-allow-html class='source-item source-aggregated' data-group-key='source-group-1' data-url='http://m&#46;toutiao&#46;com/group/7603371579141095999/?upstream&#95;biz=VolcEngine' data-id='turn2search13'><span data-allow-html class='source-item-num' data-group-key='source-group-1' data-id='turn2search13' data-url='http://m&#46;toutiao&#46;com/group/7603371579141095999/?upstream&#95;biz=VolcEngine'><span class='source-item-num-name' data-allow-html>toutiao.com</span><span data-allow-html class='source-item-num-count'>+1</span></span></span>。
2. **KV Cache 友好装配（升级）**：在"稳定前缀 + Append-Only + 检索后置"基础上，预留与 **组合式复用（Compositional Reuse）** 推理侧对接的接口，使 RAG / 长期记忆注入的动态块在不破坏前缀缓存的同时支持选择性重计算<span data-allow-html class='source-item source-aggregated' data-group-key='source-group-12' data-url='https://cloud&#46;tencent&#46;com/developer/article/2591878' data-id='turn1fetch1'><span data-allow-html class='source-item-num' data-group-key='source-group-12' data-id='turn1fetch1' data-url='https://cloud&#46;tencent&#46;com/developer/article/2591878'><span class='source-item-num-name' data-allow-html>tencent.com</span><span data-allow-html class='source-item-num-count'></span></span></span>。
3. **多 Agent 编排（升级）**：在现有规则三级路由 + 五条领域子图之上，引入 **DAG Plan & Execute + Adversarial Review（结构化分歧）**，以最小化协作范式（3-agent：Planner / Reviewer / Critic）替换朴素多 Agent 投票<span data-allow-html class='source-item source-aggregated' data-group-key='source-group-2' data-url='https://arxiv&#46;org/html/2606&#46;20058v1' data-id='turn0fetch0'><span data-allow-html class='source-item-num' data-group-key='source-group-2' data-id='turn0fetch0' data-url='https://arxiv&#46;org/html/2606&#46;20058v1'><span class='source-item-num-name' data-allow-html>arxiv.org</span><span data-allow-html class='source-item-num-count'>+1</span></span></span>。
4. **评测体系（扩容）**：在现有 `evals/eval_config.yaml` 门禁之上，对齐 **RULER v2 四类任务（Retrieval / Multi-hop / Aggregation / QA）** 与 **NoLiMa 非字面匹配**，并接入 Prometheus + Grafana 看板<span data-allow-html class='source-item source-aggregated' data-group-key='source-group-3' data-url='https://openreview&#46;net/forum?id=GzzyuhP5Kz' data-id='turn2search3'><span data-allow-html class='source-item-num' data-group-key='source-group-3' data-id='turn2search3' data-url='https://openreview&#46;net/forum?id=GzzyuhP5Kz'><span class='source-item-num-name' data-allow-html>openreview.net</span><span data-allow-html class='source-item-num-count'>+2</span></span></span>。

---

## 1. 现状与差距分析

### 1.1 已有指标（沿用 v1.0 数值）

| 指标 | 当前值 | 说明 |
|---|---|---|
| 历史上下文占用减少 | 35.63% | 相比全量拼接 |
| 16K 窗口相关历史召回率 | 87.08% | 固定 Token 预算 |
| Agent 路由准确率 | 97.55% | 规则三级路由 |
| 拒答检测召回率 | 73.33% | Evidence Gate 拒答 |
| RAG 命中率 / Hit@1 | 97.67% / 89.00% | Dense + BM25 → RRF → BGE rerank |

### 1.2 与 2025–2026 前沿的差距

| 模块 | 现状 | 2025–2026 主流方案 | 差距 |
|---|---|---|---|
| 长期记忆 | 单层摘要 + 偏好候选 | Letta 三层（Core/Recall/Archival）+ pgvector/AGE 混合索引 | 缺少 Archival 层与实体关系图谱<span data-allow-html class='source-item source-aggregated' data-group-key='source-group-4' data-url='https://help&#46;aliyun&#46;com/en/polardb/polardb&#45;for&#45;postgresql/ai&#45;agent&#45;long&#45;memory&#45;solution' data-id='turn0search1'><span data-allow-html class='source-item-num' data-group-key='source-group-4' data-id='turn0search1' data-url='https://help&#46;aliyun&#46;com/en/polardb/polardb&#45;for&#45;postgresql/ai&#45;agent&#45;long&#45;memory&#45;solution'><span class='source-item-num-name' data-allow-html>aliyun.com</span><span data-allow-html class='source-item-num-count'>+1</span></span></span> |
| KV Cache | 应用层稳定前缀策略 | 推理层组合式复用（选择性重计算、Chunk De-Noising、Smart Eviction） | 未预留推理侧接口<span data-allow-html class='source-item source-aggregated' data-group-key='source-group-5' data-url='https://cloud&#46;tencent&#46;com/developer/article/2591878' data-id='turn1fetch1'><span data-allow-html class='source-item-num' data-group-key='source-group-5' data-id='turn1fetch1' data-url='https://cloud&#46;tencent&#46;com/developer/article/2591878'><span class='source-item-num-name' data-allow-html>tencent.com</span><span data-allow-html class='source-item-num-count'>+1</span></span></span> |
| 多 Agent | LangGraph 单层子图 | DAG Plan & Execute + Adversarial Review（3-agent 结构化分歧） | 缺少显式 DAG 节点元数据、失败局部重规划与 Critic 角色<span data-allow-html class='source-item source-aggregated' data-group-key='source-group-6' data-url='https://arxiv&#46;org/html/2606&#46;20058v1' data-id='turn0fetch0'><span data-allow-html class='source-item-num' data-group-key='source-group-6' data-id='turn0fetch0' data-url='https://arxiv&#46;org/html/2606&#46;20058v1'><span class='source-item-num-name' data-allow-html>arxiv.org</span><span data-allow-html class='source-item-num-count'>+1</span></span></span> |
| 长上下文评测 | 自定义 QA 集 | RULER v2 / LongBench v2 / NoLiMa / HELMET / MRCR | 任务类型未对齐，缺失多跳与聚合<span data-allow-html class='source-item source-aggregated' data-group-key='source-group-7' data-url='https://openreview&#46;net/forum?id=GzzyuhP5Kz' data-id='turn2search3'><span data-allow-html class='source-item-num' data-group-key='source-group-7' data-id='turn2search3' data-url='https://openreview&#46;net/forum?id=GzzyuhP5Kz'><span class='source-item-num-name' data-allow-html>openreview.net</span><span data-allow-html class='source-item-num-count'>+2</span></span></span> |
| 工具互操作 | 自研 Tool Registry | MCP / A2A 协议 | 可在 Tool Registry 之上增加 MCP 适配器<span data-allow-html class='source-item source-aggregated' data-group-key='source-group-13' data-url='https://cloud&#46;tencent&#46;cn/developer/article/2718624' data-id='turn1search5'><span data-allow-html class='source-item-num' data-group-key='source-group-13' data-id='turn1search5' data-url='https://cloud&#46;tencent&#46;cn/developer/article/2718624'><span class='source-item-num-name' data-allow-html>tencent.cn</span><span data-allow-html class='source-item-num-count'></span></span></span> |

---

## 2. 设计目标与原则

| 目标 | 度量方式 | 当前基线 | 目标值 |
|---|---|---|---|
| 长会话 Token 消耗 | Context Token Reduction | 35.63% | ≥ 40% |
| 历史可追溯性 | Recall@Budget (16K) | 87.08% | ≥ 90% |
| Prefix Cache 复用 | LCPRatio | 待采集 | 相对基线 +20% |
| 首 Token 时延 | Prefill / TTFT | 待采集 | 相对基线 −15% |
| 路由与工具质量 | Router Accuracy / 无效工具调用率 | 97.55% / 待采集 | ≥ 98% / ≤ 5% |
| 拒答能力 | Refusal Recall / Precision | 73.33% / 待采集 | ≥ 85% / ≥ 80% |
| 长上下文真实能力 | RULER v2 综合得分 / NoLiMa | 待采集 | Retrieval ≥ 95%，Multi-hop ≥ 80%，Aggregation ≥ 75% |

**设计原则**：稳定性优先、可追溯、可评测、渐进式演进、与现有 `evals/eval_config.yaml` 门禁兼容、不破坏五条领域子图边界。

---

## 3. 分层记忆与上下文控制

### 3.1 三层记忆模型（对齐 Letta/MemGPT 范式）

| 层级 | 内容 | 存储位置 | 上下文策略 | FitPilot 落地点 |
|---|---|---|---|---|
| Core（活跃层） | 最近 K 轮 + 用户 Persona + 任务上下文 | Redis / 内存 | 始终保留在主上下文 | 扩展现有 `memories` API 的 session 上下文块 |
| Recall（摘要层） | 历史轮次的摘要 + embedding | PostgreSQL + pgvector（ivfflat/HNSW） | 按当前 query 向量召回 Top-N | 新增 `conversation_memory` 表 |
| Archival（原始层） | 完整原始消息、工具调用审计、文件引用 | PostgreSQL | 默认不进上下文，支持精确回溯 | 沿用现有 `PostgresCheckpointSaver` 的事件流，扩展字段 |

> 说明：Letta 2025 年实测显示，仅用文件系统存档即可在 LoCoMo 上达 74% 准确率，**关键不是工具花哨，而是分层清晰 + 可检索**；本方案选择 PostgreSQL + pgvector 是与 FitPilot 现有技术栈（PG 已是权威源）一致的最优解<span data-allow-html class='source-item source-aggregated' data-group-key='source-group-14' data-url='https://www&#46;letta&#46;com/blog/benchmarking&#45;ai&#45;agent&#45;memory/' data-id='turn2search4'><span data-allow-html class='source-item-num' data-group-key='source-group-14' data-id='turn2search4' data-url='https://www&#46;letta&#46;com/blog/benchmarking&#45;ai&#45;agent&#45;memory/'><span class='source-item-num-name' data-allow-html>letta.com</span><span data-allow-html class='source-item-num-count'></span></span></span>。

### 3.2 数据模型（新增迁移 `0012_conversation_memory.sql`）

