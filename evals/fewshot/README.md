# 小评测总集（small / fewshot）

目录：`evals/fewshot/`  
CLI：`--suite-set small`  
用途：**快速冒烟、CI 门禁、大集种子对照**。

与大集对照见 [`../large/README.md`](../large/README.md)；总览见 [`../README.md`](../README.md)。

## 定位

| 项 | 说明 |
|----|------|
| 角色 | 少样本**种子集** + 短回归集 |
| 设计原则 | 题少、可人工审、标签可信；覆盖每层主路径即可 |
| 与大集关系 | 大集生成会**读取**本目录种子，但**不会覆盖**本目录 |
| 阈值 | 与大集共用 [`../eval_config.yaml`](../eval_config.yaml)，只换用例路径 |

## 当前规模（合计 125）

| 文件 | 条数 | 测什么 |
|------|------|--------|
| `golden_rag.json` | 50 | 在线检索 Hit / MRR / nDCG |
| `agent_routing_cases.json` | 16 | 意图路由 |
| `golden_rag_offline.json` | 16 | 离线 fixture 检索 / 拒答 |
| `no_answer_cases.json` | 10 | 拒答正负样本 |
| `plan_cases.json` | 8 | 训练计划硬约束 |
| `parsing_cases.json` | 6 | 多格式解析 |
| `safety_cases.json` | 6 | 风险识别 / 周对齐 |
| `meal_cases.json` | 5 | 食谱宏量 / 忌口 |
| `generation_cases.json` | 5 | 引用与检索端到端（静态规则） |
| `generation_online_cases.json` | 3 | LLM-as-judge（可选） |

## 构建方式

小集以**人工 / 半人工精选**为主，不是脚本凑数扩写。

### RAG（`golden_rag.json`）

1. 题目锚定 `knowledge_base/raw` 真实文档（或已入库 chunk）。
2. 每题含 `query` + `expect_any`（检索上下文中应出现的关键词 / 数字 / 文档片段）。
3. 部分题带 `relevance`（grade 2=核心，1=相关），供 nDCG。
4. 设计目标：问句可读、证据可核对；**不追求条数**。

### 离线 RAG（`golden_rag_offline.json`）

- 锚定 [`../rag_fixture/`](../rag_fixture/) 固定语料，保证 CI 可复现、不依赖线上 Qdrant 模型漂移。
- 含可答题与拒答题。

### 其余层

| 层 | 构建要点 |
|----|----------|
| parsing | 手写多格式样例（txt/md/csv/json/html/jsonl） |
| no_answer | 应回答 vs 应拒答各若干条 |
| generation | 静态引用规则 + 少量 e2e |
| generation_online | 忠实回答 / 幻觉对照（默认模块关闭） |
| agent | 覆盖主要 `expect_intent` |
| plan | 正例 + 典型违规负例 |
| meal | 小食物集 + 目标宏量；含 OR-Tools / greedy |
| safety | high/low 风险 + weekly_alignment |

## 如何使用

```powershell
cd D:\FitPilot\backend
uv run python main.py eval-gate --suite-set small
uv run python main.py eval-all --suite-set small
uv run python main.py eval --suite-set small
```

单文件：

```powershell
uv run python main.py eval --suite ..\evals\fewshot\golden_rag.json
```

## 维护建议

- **优先改小集**：发现漏测或错标时，先修正 fewshot，再决定是否刷新大集。
- 新增主题时：小集加 1–3 条「代表题」，大集用生成脚本扩覆盖。
- 不要把大集裁剪结果写回本目录。

## 相关脚本 / 文档

- 大集重生（读本目录种子）：`scripts/regenerate_large_suites.py`
- RAG 大集从 KB 出题：`scripts/generate_rag_suite_from_kb.py`
- 评估说明：[`docs/EVAL.md`](../../docs/EVAL.md)
