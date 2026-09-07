# FitPilot 评估（Eval）

FitPilot 提供 **多层评估编排**（`eval-all`）与 **RAG 单层评估**（`eval`），用于回归验收。  
单元测试（`pytest`）不替代评估；评估依赖真实索引/服务的层需先 `ingest`。

## 大 / 小评测总集

| 规模 | 目录 | 参数 | 用途 |
|------|------|------|------|
| **large** | `evals/large/*.json` | `--suite-set large`（默认） | 发布前容量回归 |
| **small** | `evals/fewshot/*.json` | `--suite-set small` | 快速冒烟、CI 门禁 |

生成大总集（推荐）：`python scripts/regenerate_large_suites.py`（小集同款：有多少造多少）。  
RAG 也可单独：`python scripts/generate_rag_suite_from_kb.py --target 300`。  
旧版配额扩写：`python scripts/generate_large_eval_suites.py`。  
目录说明见 [`evals/README.md`](../evals/README.md)。

## 模块一览

| 层 | 模块 | 评测集文件 | 默认启用 | 说明 |
|----|------|------------|----------|------|
| 1 | parsing | `parsing_cases.json` | ✅ | 多格式解析 |
| 2 | retrieval | `golden_rag.json` | ✅ | Hit@K / Precision@K / TermRecall@K / MRR / nDCG / 时延 |
| 2b | no_answer | `no_answer_cases.json` | ✅ | 拒答正负样本 |
| 3 | generation | `generation_cases.json` | ✅ | 静态规则 + 可选 e2e 检索 |
| 3b | generation_online | `generation_online_cases.json` | ❌ | LLM-as-judge（`--online`） |
| 4 | agent | `agent_routing_cases.json` | ✅ | 意图 / Macro-F1 |
| 5 | plan | `plan_cases.json` | ✅ | 训练硬约束 |
| 6 | meal | `meal_cases.json` | ✅ | 宏量误差 / 忌口 |
| 7 | safety | `safety_cases.json` | ✅ | 风险词 / 周联合调整 |
| 8 | context_kv | `context_kv_cases.json` | ✅ | 长上下文占用减少 / Recall@Budget / LCP / 三层路由 / DAG |

配置：[`evals/eval_config.yaml`](../evals/eval_config.yaml)（阈值与模块开关的唯一权威）。

## 命令

```powershell
cd D:\FitPilot\backend
$env:PYTHONPATH="D:\FitPilot\backend"
$env:NO_PROXY="127.0.0.1,localhost"

# RAG 单层（需已 ingest + Qdrant）
uv run python main.py eval --suite-set large
uv run python main.py eval --suite-set small
uv run python main.py eval --suite ..\evals\large\golden_rag.json --top-k 5

# 多层全量
uv run python main.py eval-all --suite-set large
uv run python main.py eval-all --suite-set small --out ..\evals\reports\full_eval.json

# CI 离线门禁（建议 small）
uv run python main.py eval-gate --suite-set small
uv run python main.py eval-gate --suite-set large --out ..\evals\reports\ci_gate.json

# 写入 Postgres evaluation_* 表
uv run python main.py eval-all --suite-set large --persist

# 启用 LLM-as-judge（需 Ollama + OLLAMA_MODEL_JUDGE）
uv run python main.py eval-all --suite-set small --online --persist

# 分项
uv run python main.py eval-no-answer --suite-set small
uv run python main.py eval-agent --suite-set large
```

## 进度条

交互终端下各层用例循环会显示 `tqdm` 进度条（stderr）；`eval-all` / `eval-gate` 还会打印层标题。

```powershell
# 强制开启（即便非 TTY，例如重定向日志时）
$env:FITPILOT_EVAL_PROGRESS="1"
uv run python main.py eval-gate --suite-set small

# 强制关闭（CI 默认因非 TTY 已关闭）
$env:FITPILOT_EVAL_PROGRESS="0"
```

## 指标含义

| 指标 | 含义 |
|------|------|
| `hit_rate` / `hit@K` | Top-K 是否出现「至少一个」相关 chunk（`expect_any` 命中）；Hit@K=1 iff Precision@K ≥ 1/K |
| `precision@K` | Top-K 中相关 chunk 占比（榜有多纯） |
| `term_recall@K` | Top-K 覆盖的 `expect_any` 词数 / \|expect_any\|（关键词覆盖召回） |
| `anchor_chunk@K` / `anchor_doc@K` | 有 `source_chunk_id` / `source_document_id` 时，锚点是否进入 Top-K（仅对该子集平均） |
| `mrr` | Mean Reciprocal Rank（仅 chunk 级 rank；context 回退不计入） |
| `ndcg@K` | 排序质量（有 `relevance` grade 时更有信息量） |
| `citation_rate` | 返回中带 citation 的占比 |
| `avg_latency_ms` | 混合检索 + 组上下文平均耗时（不含 Ollama 生成） |
| Agent accuracy / Macro-F1 | 意图分类准确率与宏平均 F1 |
| no_answer recall/precision | 应拒答召回 / 误拒答精度 |
| context reduction_ratio | 相对全量历史拼接的 Token 占用减少比例 |
| recall_at_budget | 固定 Token 预算下相关历史轮次召回率 |
| lcp_ratio | 稳定前缀最长公共前缀比（KV Cache 友好度） |
| orchestrator_pass | ECD/DAG 节点与依赖结构用例通过率 |

**Hit 高 ≠ Precision / TermRecall 高。** Hit@5 只需 top-5 里有一条相关；Precision@5 要求多数相关；TermRecall@5 要求 `expect_any` 词袋覆盖率高。三者可同时成立（例如 Hit@5≈98% 而 Precision@5≈0.6）。

`precision_at_5` / `term_recall_at_5` 可在 `eval_config.yaml` 设门禁；**默认 0=不生效**，Hit@K / MRR 仍为主门禁。观察目标（suite v4 + eval `rerank_top_k` 对齐后）：Precision@5 ≥ 0.70、TermRecall@5 ≥ 0.80，Hit@5 仍 ≥ 0.90。

大集 `golden_rag`（`fitpilot-golden-rag-kb-v4`）出题约束：`expect_any` 为源 chunk 2–3 核心词（禁 FDC/裸年份/document_id slug）；hard 改写禁止半截「相关内容」占位；主题-文档门控。在线评测对 `hybrid_retrieve` 传入 `rerank_top_k=max(K)`，避免默认精排截断 4 条导致 @5 指标虚低。
## 评测集约定

- **retrieval**：`expect_any` 任一关键词出现在 chunk/上下文即 HIT  
- **no_answer**：需同时包含 `expect_no_answer: true` 与 `false` 样本  
- **generation**：`mode=static` 测规则；`mode=e2e_retrieve` 测真实检索（服务不可用时 `skip_on_error` 跳过）  
- **generation_online**：可用 `expect_fail: true` 测幻觉应被裁判打低分  

## 代码

- `backend/app/eval/suite_set.py` — `--suite-set` 路径解析  
- `backend/app/eval/full_eval.py` — 多层编排  
- `backend/app/eval/*_eval.py` — 各层 runner  
- `backend/app/eval/eval_persistence.py` — `--persist` 写入  
- `backend/app/cli.py` — `eval` / `eval-all` / `eval-gate` / `eval-agent` / `eval-no-answer`

## 与 pytest / status 的关系

```powershell
uv run python main.py test            # 单元/组件测试（含离线评估层）
uv run python main.py eval            # 依赖真实 Qdrant/索引（默认 large）
uv run python main.py eval-all        # 多层回归（默认 large）
uv run python main.py eval-gate --suite-set small   # 与 CI 一致
uv run python main.py status --local  # 依赖就绪探测
```
