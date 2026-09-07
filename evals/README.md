# FitPilot 评测集说明

## 两套规模

| 规模 | 目录 | CLI | 用途 |
|------|------|-----|------|
| **large**（大评测总集） | [`large/`](large/) | `--suite-set large`（默认） | 容量回归、发布前全量 |
| **small**（小评测总集） | [`fewshot/`](fewshot/) | `--suite-set small` | 快速冒烟、CI 门禁、种子对照 |

每套的**信息与构建方式**见目录内 README：

- 大集：[`large/README.md`](large/README.md)
- 小集：[`fewshot/README.md`](fewshot/README.md)

权威阈值与模块开关仍在 [`eval_config.yaml`](eval_config.yaml)。`--suite-set` 只切换各层用例路径，不改阈值。

当前大集规模见 [`large/suite_manifest.json`](large/suite_manifest.json)。

## 目录结构

```text
evals/
├── eval_config.yaml      # 模块开关与阈值
├── large/                # 大评测总集
├── fewshot/              # 小评测总集（种子）
├── rag_fixture/          # 离线 RAG fixture
└── reports/              # 运行报告输出
```

## 生成 / 刷新大总集

```powershell
cd D:\FitPilot
# 推荐：按小集同款方式全量重生（有多少造多少）
.\backend\.venv\Scripts\python.exe scripts\regenerate_large_suites.py

# 旧版配额扩写（仍可用）：
.\backend\.venv\Scripts\python.exe scripts\generate_large_eval_suites.py
# 仅 RAG：
.\backend\.venv\Scripts\python.exe scripts\generate_rag_suite_from_kb.py --target 300
```

- `golden_rag`：从当前 `knowledge_base` BM25 chunk 按主题分层出题
- 其余层：fewshot 种子 + 唯一模板网格（**不凑整数**）
- 写入 `evals/large/`，**不会覆盖 fewshot**
- 实际条数见 `suite_manifest.json`

## 命令示例

```powershell
cd D:\FitPilot\backend
# 大总集（默认）
uv run python main.py eval-all --suite-set large
uv run python main.py eval --suite-set large
uv run python main.py eval-gate --suite-set large

# 小总集（快速 / CI）
uv run python main.py eval-all --suite-set small
uv run python main.py eval-gate --suite-set small
uv run python main.py eval-agent --suite-set small

# 仍可用 --suite 显式指定单个 JSON（优先于 --suite-set）
uv run python main.py eval --suite ..\evals\fewshot\golden_rag.json
```

离线 fixture 语料在 `evals/rag_fixture/`（与规模无关）。更完整说明见 [`docs/EVAL.md`](../docs/EVAL.md)。

交互终端下默认显示用例进度条；可用 `FITPILOT_EVAL_PROGRESS=0|1` 强制关/开。
