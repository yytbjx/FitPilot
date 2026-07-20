# 从 llm-knowledge-base 迁移的能力（历史说明）

对照参考项目 `llm-knowledge-base`，FitPilot **有选择地**吸收运维与质量闭环能力，**不**替换本仓库的 Vue / Postgres / LangGraph 域模型，也不整包迁入 Gradio / BGE-M3 / 完整 LangChain RAGAS 栈。

> **模型与数据独立**：FitPilot 的 Embedding / Reranker 存放于本仓库 `models/`，为真实目录副本，**不再**使用指向其他仓库的目录联接。两项目可分别迁移到任意路径，互不影响。

## 已迁移

| 能力 | FitPilot 位置 | 说明 |
|------|---------------|------|
| 输入消毒 | `backend/app/core/input_sanitizer.py` → Agent `/chat` `/tasks` | Prompt Injection / 危险指令拦截 |
| 本地 Trace | `backend/app/core/tracing.py` + `GET /agent/traces` | 内存步骤追踪（检索/LLM） |
| Prometheus | `backend/app/core/metrics.py` + `/metrics` | 检索/LLM/Token/入库/消毒计数与时延 |
| 幂等入库 | `backend/app/rag/ingest.py` | 按 `document_id` 先删后写 |
| 评估深化 | `backend/app/eval/rag_eval.py` + `evals/eval_config.*` | Hit@K、MRR、JSON/MD 报告 |
| 状态探测 | `fitpilot status` / `status --local` | Postgres/Redis/Qdrant/Ollama |
| CI | `.github/workflows/ci.yml` | 无外部依赖的核心 pytest |

## 刻意未迁移

- Gradio UI、代码 AST 解析语料管线
- RAGAS / LLM-as-judge 全量评测（可用扩展，见 `docs/EVAL.md`）
- 与参考项目相同的 BGE-M3 / 稀疏向量方案（本项目用既定 embedding + BM25 + rerank）

## 常用命令

```powershell
cd D:\FitPilot\backend
uv run python main.py status --local
uv run python main.py eval --out ..\evals\reports\last.json
# Agent Trace（需登录后）: GET /api/agent/traces
# 指标: GET /metrics
```
