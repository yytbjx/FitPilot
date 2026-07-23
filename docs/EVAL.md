# FitPilot 评估（Eval）

FitPilot 提供 **多层评估编排**（`eval-all`）与 **RAG 单层评估**（`eval`），用于回归验收。  
单元测试（`pytest`）不替代评估；评估依赖真实索引/服务的层需先 `ingest`。

## 模块一览（9 层）

| 层 | 模块 | 评测集 | 默认启用 | 说明 |
|----|------|--------|----------|------|
| 1 | parsing | `parsing_cases.json` | ✅ | 多格式解析 |
| 2 | retrieval | `golden_rag.json` | ✅ | Hit@K / MRR / 引用 / 时延 |
| 2b | no_answer | `no_answer_cases.json` | ✅ | 拒答正负样本 |
| 3 | generation | `generation_cases.json` | ✅ | 静态规则 + 可选 e2e 检索 |
| 3b | generation_online | `generation_online_cases.json` | ❌ | LLM-as-judge（`--online`） |
| 4 | agent | `agent_routing_cases.json` | ✅ | 意图 / Macro-F1 |
| 5 | plan | `plan_cases.json` | ✅ | 训练硬约束 |
| 6 | meal | `meal_cases.json` | ✅ | 宏量误差 / 忌口 |
| 7 | safety | `safety_cases.json` | ✅ | 风险词 / 周联合调整 |

配置：[`evals/eval_config.json`](../evals/eval_config.json)（与 [`eval_config.yaml`](../evals/eval_config.yaml) **同步**）。

## 命令

```powershell
cd D:\FitPilot\backend
$env:PYTHONPATH="D:\FitPilot\backend"
$env:NO_PROXY="127.0.0.1,localhost"

# RAG 单层（需已 ingest + Qdrant）
uv run python main.py eval
uv run python main.py eval --suite ..\evals\golden_rag.json --top-k 5 --out ..\evals\reports\rag_last.json

# 多层全量
uv run python main.py eval-all
uv run python main.py eval-all --out ..\evals\reports\full_eval.json --md ..\evals\reports\full_eval.md

# CI 离线门禁（parsing / agent / plan / meal / safety，不依赖 Qdrant）
uv run python main.py eval-gate
uv run python main.py eval-gate --out ..\evals\reports\ci_gate.json

# 写入 Postgres evaluation_* 表
uv run python main.py eval-all --persist

# 启用 LLM-as-judge（需 Ollama + OLLAMA_MODEL_JUDGE）
uv run python main.py eval-all --online --persist

# 分项
uv run python main.py eval-no-answer
uv run python main.py eval-agent

# 仓库根目录等价
cd D:\FitPilot
python main.py eval-all
```

## 指标含义

| 指标 | 含义 |
|------|------|
| `hit_rate` | 命中 `expect_any` 的用例占比（含 context 回退命中，但不伪造 rank） |
| `hit@K` | **chunk 级**首个相关排在 top-K 内的占比 |
| `mrr` | Mean Reciprocal Rank（仅 chunk 级 rank；context 回退不计入） |
| `citation_rate` | 返回中带 citation 的占比 |
| `avg_latency_ms` | 混合检索 + 组上下文平均耗时（不含 Ollama 生成） |
| Agent accuracy / Macro-F1 | 意图分类准确率与宏平均 F1 |
| no_answer recall/precision | 应拒答召回 / 误拒答精度 |

## 评测集约定

- **retrieval**：`expect_any` 任一关键词出现在 chunk/上下文即 HIT  
- **no_answer**：需同时包含 `expect_no_answer: true` 与 `false` 样本  
- **generation**：`mode=static` 测规则；`mode=e2e_retrieve` 测真实检索（服务不可用时 `skip_on_error` 跳过）  
- **generation_online**：可用 `expect_fail: true` 测幻觉应被裁判打低分  

## 代码

- `backend/app/eval/full_eval.py` — 多层编排  
- `backend/app/eval/*_eval.py` — 各层 runner  
- `backend/app/eval/eval_persistence.py` — `--persist` 写入  
- `backend/app/cli.py` — `eval` / `eval-all` / `eval-agent` / `eval-no-answer`

## 与 pytest / status 的关系

```powershell
uv run python main.py test            # 单元/组件测试（含离线评估层）
uv run python main.py eval            # 依赖真实 Qdrant/索引
uv run python main.py eval-all        # 多层回归
uv run python main.py status --local  # 依赖就绪探测
```
