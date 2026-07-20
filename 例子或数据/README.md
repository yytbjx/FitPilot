# 例子或数据：外部模板与数据集用法

本目录放置参考项目与开放数据集，用于充实 FitPilot，而**不是**让 FitPilot 直接跑 Next.js 应用。

## 目录

| 路径 | 用途 |
|------|------|
| `workout-cool-main/` | 产品与数据模型参考（动作筛选、训练会话、计划层级） |
| `exercises-dataset-main/` | **动作库数据源**（约 1324 条，MIT 文本；媒体非 MIT） |
| `FoodData_Central_foundation_food_json_2026-04-30.json` | USDA 英文原版（回退） |
| `FoodData_Central_foundation_food_2026-04-30_中文翻译包/` | **推荐**：中文名 + 宏量对照，用于食物库 |

## 我们采纳的设计

1. **标准化动作库**（Postgres `exercises`）— 类似 workout.cool 的 Exercise 目录  
2. **器械 × 部位筛选** — Agent / 计划预览按档案选动作；`POST /exercises/shuffle`  
3. **动作说明进 RAG** — 可选 `--to-qdrant`  
4. **食物宏量库** — 中文常用种子 + USDA Foundation（中文名优先）  
5. **知识库只收精简 FDC 资料** — 宏量 JSON + 摘要 MD + 对照 CSV，不全量拷贝 12MB+ 营养数组 JSON  

## 未照搬的部分

- Next.js / Prisma / BetterAuth / RevenueCat / Stripe  
- Gym Visual 的 GIF/图片（版权限制，仅文本入库）  
- USDA 完整微量营养素数组进 Qdrant  

## 导入命令

```powershell
cd D:\FitPilot
$env:PYTHONPATH="D:\FitPilot\backend"
$env:NO_PROXY="127.0.0.1,localhost"

.\backend\.venv\Scripts\alembic.exe upgrade head

# 动作库
.\backend\.venv\Scripts\python.exe scripts\seed_exercises.py

# 食物：先整理中文包 → 再写入 Postgres
.\backend\.venv\Scripts\python.exe scripts\prepare_fdc_kb.py
.\backend\.venv\Scripts\python.exe scripts\seed_foods.py

# 知识库（含 FDC 宏量摘要 MD）
.\backend\.venv\Scripts\python.exe scripts\ingest_kb.py
```

API：`GET /exercises`、`POST /exercises/shuffle`、`GET /foods`  
前端：侧栏「动作库」「食物库」
