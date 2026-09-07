# FitPilot 知识库公开资料目录说明

## 目录结构

```text
knowledge_base/raw/
├── *.md                         # 项目种子中文语料
├── curated/                     # 整理后的公开科普（MD/DOCX）
├── external/                    # 官方/公开 PDF
└── images/                      # 图片（当前无 OCR，仅占位可检索说明）
```

## 已收录（本次）

| 文件 | 类型 | 说明 |
|------|------|------|
| `external/US_Physical_Activity_Guidelines_2nd.pdf` | PDF | 美国 HHS《Physical Activity Guidelines for Americans》第 2 版（公开可下载） |
| `external/WHO_PA_2020.pdf` | PDF | WHO《Guidelines on physical activity and sedentary behaviour》(2020) 官方全文（已下载入库） |
| `external/CN_higher_level_fitness_public_service_system_opinions.pdf` | PDF | 中办国办《关于构建更高水平的全民健身公共服务体系的意见》（体育总局公开 PDF） |
| `external/CDC_NCHS_water_intake_databrief_242.pdf` | PDF | CDC/NCHS 成人饮水量 Data Brief 242 |
| `curated/who_pa_2020_core.md` | MD | WHO 2020 指南公开要点摘录（中文整理，便于检索） |
| `curated/cn_dietary_guidelines_2022_core.md` | MD | 中国居民膳食指南（2022）八准则公开解读整理 |
| `curated/strength_training_basics.md` | MD | 力量训练与恢复公开原则整理 |
| `curated/hydration_training.md` | MD | 饮水与训练表现科普 |
| `curated/protein_fatloss_faq.docx` | DOCX | 减脂蛋白问答演示语料 |
| `curated/guidelines/*.md` | MD | 由公开网页清洗生成的指南/事实清单（WHO 中文、CDC/NHS、中国营养学会、体育总局科学健身等）；每篇含来源 URL |
| `curated/public_web/*.html` | HTML | 上述网页原始快照（**不入库**，仅溯源；入库目录已跳过 `public_web`） |
| `curated/fdc/` | CSV/JSON/MD | USDA Foundation Foods **中文翻译包**精简资料（宏量对照、营养素词典、RAG 摘要） |
| `uploads/` | 多格式 | `POST /knowledge/ingest/upload` 上传落盘位置 |
| `images/eat_move_balance.png` | PNG | 「吃动平衡」示意图（可配 OCR 或同名 md） |
| `*.md`（根目录种子） | MD | protein / fat_loss / safety 等项目种子语料 |

> 最近一次 `--reset` 入库约 **58** 篇文档 / **4148** chunks；主题容量评估为 **16/16 强主题**，粗估可支撑 **200–500+** 检索评测样本。

## 公开语料拉取

```powershell
cd D:\FitPilot
.\backend\.venv\Scripts\python.exe scripts\fetch_public_kb_sources.py
.\backend\.venv\Scripts\python.exe scripts\expand_rag_fixture_from_guidelines.py
.\backend\.venv\Scripts\python.exe scripts\ingest_kb.py --reset
.\backend\.venv\Scripts\python.exe scripts\assess_kb_eval_capacity.py
```

## USDA 中文包如何进入项目

1. 源目录：`例子或数据/FoodData_Central_foundation_food_2026-04-30_中文翻译包/`  
2. 整理命令：`scripts/prepare_fdc_kb.py` → 复制对照表并生成  
   - `knowledge_base/raw/curated/fdc/foundation_foods_macros_zh.json`（Postgres 导入）  
   - `knowledge_base/raw/curated/fdc/usda_foundation_foods_macros_zh.md`（RAG）  
3. 导入 Postgres：`scripts/seed_foods.py`（保留中文种子 + USDA 363 条）  
4. **大体积**中文值版 / 中英双语完整 JSON **不拷进知识库**（避免把完整 nutrient 数组灌进 Qdrant）

## 建议手动补齐（可选）

当前官方 PDF 已齐：**WHO 2020**、**US PA Guidelines 2nd**。后续可再补其他开放文档到 `raw/external/` 后执行 `scripts/ingest_kb.py`（大批量换料建议加 `--reset`）。

> 说明：早期 ACLM 站点下载超时失败，未入库；不影响现有 WHO/美国指南检索。

## 入库前要不要清库？

| 数据库 | 要不要清 | 说明 |
|--------|----------|------|
| **Postgres**（用户/密码/计划/打卡） | **不要清** | 与知识库无关；清了会丢账号与业务数据 |
| **Qdrant `fitpilot_knowledge`** | **建议重建** | 大批量换语料/换 Embedding 时用 `--reset`，避免旧向量残留 |
| **BM25 本地索引** | 随 `--reset` 一并清空 | `ingest_kb.py --reset` 已处理 |

## 推荐入库命令

```powershell
cd D:\FitPilot
$env:PYTHONPATH="D:\FitPilot\backend"
$env:NO_PROXY="127.0.0.1,localhost"
# 不要设 RAG_OFFLINE=1
.\backend\.venv\Scripts\python.exe scripts\ingest_kb.py --reset
```

> 大 PDF 解析与向量化可能需数分钟，属正常。`--reset` 会重建 Qdrant 集合，并以当前语料**全量重建** BM25（不合并历史噪声）。

## 与回答链路的关系

入库的是**证据原文**；对话时由 **Ollama 基于检索证据生成**自然语言回答并附引用，不是把 Qdrant 原文整段贴回。
