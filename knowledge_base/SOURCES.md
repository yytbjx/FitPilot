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
| `curated/who_pa_2020_core.md` | MD | WHO 2020 指南公开要点摘录（中文整理，便于检索） |
| `curated/cn_dietary_guidelines_2022_core.md` | MD | 中国居民膳食指南（2022）八准则公开解读整理 |
| `curated/strength_training_basics.md` | MD | 力量训练与恢复公开原则整理 |
| `curated/hydration_training.md` | MD | 饮水与训练表现科普 |
| `curated/protein_fatloss_faq.docx` | DOCX | 减脂蛋白问答演示语料 |
| `curated/fdc/` | CSV/JSON/MD | USDA Foundation Foods **中文翻译包**精简资料（宏量对照、营养素词典、RAG 摘要） |
| `uploads/` | 多格式 | `POST /knowledge/ingest/upload` 上传落盘位置 |
| `images/eat_move_balance.png` | PNG | 「吃动平衡」示意图（可配 OCR 或同名 md） |
| `*.md`（根目录种子） | MD | protein / fat_loss / safety 等项目种子语料 |

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

> 大 PDF 解析与向量化可能需数分钟，属正常。本次已成功入库约 **431** chunks（含美国身体活动指南 PDF）。

## 与回答链路的关系

入库的是**证据原文**；对话时由 **Ollama 基于检索证据生成**自然语言回答并附引用，不是把 Qdrant 原文整段贴回。
