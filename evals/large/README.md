# 大评测总集（large）

目录：`evals/large/`  
CLI：`--suite-set large`（默认）  
用途：**容量回归、发布前全量、分层难度与多样性检查**。

与小集对照见 [`../fewshot/README.md`](../fewshot/README.md)；总览见 [`../README.md`](../README.md)。  
实际条数以同目录 [`suite_manifest.json`](suite_manifest.json) 为准。

## 定位

| 项 | 说明 |
|----|------|
| 角色 | 在小集种子之上，按**小集同款出题方式**放大覆盖 |
| 设计原则 | **有多少造多少**，不凑 200/250/300；标签尽量可核对 |
| 与小集关系 | 读取 `evals/fewshot/`，**不覆盖**小集 |
| 阈值 | 与小集共用 [`../eval_config.yaml`](../eval_config.yaml) |

## 当前规模（合计约 784）

> 下表为最近一次 `regenerate_large_suites.py` 写入结果；若你本地重跑过，以 `suite_manifest.json` 为准。

| 文件 | 条数 | 测什么 |
|------|------|--------|
| `golden_rag.json` | 300 | 在线检索（KB 锚定 + 难度分层） |
| `agent_routing_cases.json` | 163 | 意图路由（模板×尾缀网格） |
| `meal_cases.json` | 107 | 食谱宏量 / 忌口 |
| `parsing_cases.json` | 54 | 多格式解析 |
| `golden_rag_offline.json` | 44 | 离线 fixture 检索 / 拒答 |
| `no_answer_cases.json` | 36 | 拒答正负样本 |
| `safety_cases.json` | 27 | 风险 / 周对齐 |
| `plan_cases.json` | 23 | 训练计划硬约束 |
| `generation_cases.json` | 17 | 引用与 e2e |
| `generation_online_cases.json` | 13 | LLM-as-judge（可选） |

## 构建方式

推荐入口：

```powershell
cd D:\FitPilot
.\backend\.venv\Scripts\python.exe scripts\regenerate_large_suites.py
```

模式：`fewshot_style_capacity`（见 `suite_manifest.json`）。

### 1. `golden_rag`（与小集同思路，规模更大）

脚本：`scripts/generate_rag_suite_from_kb.py`（由重生脚本调用）

1. 读取 `knowledge_base/bm25_index.json` 的 chunk。
2. 按主题分层抽样，限制单文档 / 单主题膨胀。
3. 每题：`query` + `expect_any`（必须能在源 chunk 中核对）+ 可选 `relevance`。
4. 并入 fewshot 锚点；每锚点最多少量 hard 改写。
5. 难度：easy / medium / hard（hard 削弱问句字面泄漏，降低虚高 hit_rate）。
6. **v4**：`expect_any` 收紧为源 chunk 2–3 核心词（禁 FDC/裸年份/id slug）；hard 禁止半截「相关内容」占位；主题-文档门控。

**读指标建议：** 不要只看 hit_rate；同时看 **Precision@K**（榜纯度）、**TermRecall@K**（关键词覆盖）、MRR、nDCG@5，并关注 `difficulty=hard` 子集。KB 锚定题可看 `anchor_doc@K` / `anchor_chunk@K`。

关系速记：`Hit@K = 1` 当且仅当 `Precision@K ≥ 1/K`；Hit 高而 Precision 低 = 总能沾边但榜上掺水。观察目标：Precision@5 ≥ 0.70、TermRecall@5 ≥ 0.80（yaml 默认仍为 0，不硬 fail CI）。

### 2. 其余层（种子 + 唯一模板网格）

| 层 | 构建要点 |
|----|----------|
| offline RAG | fewshot 题 + 限量改写 + OOD 拒答（绑 `rag_fixture`） |
| parsing | 主题 × 格式（txt/md/csv/json/html/jsonl）各一条量级 |
| no_answer | 可答题 / 拒答题模板 + 限量 hard 改写 |
| generation | 静态模板 + e2e 查询（含少量 hard） |
| generation_online | 忠实回答 + `expect_fail` 对照 |
| agent | 各意图模板 × 安全尾缀；短句意图不加尾缀 |
| plan | 正例动作网格 + 固定违规负例 |
| meal | 种子/全池模板 × 忌口 × 轻扰动 + 少量 `expect_ok=false` |
| safety | 高风险词 / 低风险问句 / 周对齐若干组合 |

**不做的事：** 用「（样本 N）」无限灌水凑整数。

### 3. 其他脚本（可选）

| 脚本 | 用途 |
|------|------|
| `scripts/generate_rag_suite_from_kb.py` | 仅刷新 RAG 大集 |
| `scripts/generate_large_eval_suites.py` | 旧版「配额扩写」路径（不推荐作主流程） |
| `scripts/prune_large_suites.py` | 对已有大集去重封顶（历史工具） |

## 如何使用

```powershell
cd D:\FitPilot\backend
uv run python main.py eval-all --suite-set large
uv run python main.py eval --suite-set large
uv run python main.py eval-gate --suite-set large
```

在线 retrieval 需先 ingest（Qdrant + 模型）；离线层依赖 `evals/rag_fixture/`。

## 维护建议

1. **ingest / 知识库变更后**：至少重跑 RAG（`generate_rag_suite_from_kb.py` 或完整 `regenerate_large_suites.py`）。
2. **改规则 / 意图 / 校验逻辑后**：重跑对应层或整包重生。
3. 报告规模时同时看：`n_cases`、`unique` 主题/意图、`suite_manifest.json`。
4. 小集修正后，再重生大集，避免大集与种子语义漂移。

## 相关文档

- 小集说明：[`../fewshot/README.md`](../fewshot/README.md)
- 评测总览：[`../README.md`](../README.md)
- 评估模块与阈值：[`docs/EVAL.md`](../../docs/EVAL.md)
- 配置：[`../eval_config.yaml`](../eval_config.yaml)
