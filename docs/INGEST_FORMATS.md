# FitPilot 知识入库：多格式说明

解析实现位于 `backend/app/rag/parsing/`（注册表架构）。  
切块 / 向量化 / Qdrant+BM25 对所有格式统一；**差异只在「解析成 Markdown 文本」**。

## 支持格式

| 分组 | 后缀 | 解析方式 |
|------|------|----------|
| 文本 | `.md` `.markdown` `.txt` `.rst` `.log` | 直接读文本（自动尝试 utf-8/gb18030） |
| Office | `.docx` | 段落 + 表格 → Markdown |
| Office | `.pptx` | 每页幻灯片文字/表格 |
| Office | `.xlsx` | 工作表 → Markdown 表（可截断行数） |
| PDF | `.pdf` | 按页抽文本；扫描件过短会跳过 |
| Web | `.html` `.htm` `.xhtml` | BeautifulSoup 去脚本后抽正文 |
| Web | `.xml` | 树形字段展开 |
| 数据 | `.csv` `.tsv` | 表头+行 → Markdown 表 |
| 数据 | `.json` `.jsonl` `.ndjson` | 对象数组优先表格化，否则展平 |
| 图片 | `.png` `.jpg` `.jpeg` `.webp` `.gif` `.bmp` `.tif` `.tiff` | 元信息 + 可选 OCR / 同名旁路 md |

旧版 `.xls` 请另存为 `.xlsx`。

## 环境变量（截断与 OCR）

| 变量 | 默认 | 含义 |
|------|------|------|
| `RAG_CSV_MAX_ROWS` | 300 | CSV/TSV 最大行数 |
| `RAG_JSON_MAX_ITEMS` | 200 | JSON 数组最大展示条数 |
| `RAG_JSON_MAX_BYTES` | 8388608 | 单 JSON 文件体积上限 |
| `RAG_PDF_MAX_PAGES` | 空=不限 | PDF 最多解析页数 |
| `RAG_SHEET_MAX_ROWS` | 200 | Excel 每表最大行 |
| `RAG_SHEET_MAX_SHEETS` | 10 | Excel 最多工作表 |
| `RAG_ENABLE_OCR` | false | 图片是否 OCR |
| `RAG_OCR_LANG` | chi_sim+eng | tesseract 语言 |

OCR 可选依赖（未默认安装）：`pytesseract` + 系统 Tesseract，或 `easyocr`。

## 命令

```powershell
cd D:\FitPilot
$env:PYTHONPATH="D:\FitPilot\backend"
.\backend\.venv\Scripts\python.exe scripts\ingest_kb.py
# 或 --reset 重建 Qdrant 知识集合
```

API：

- `GET /knowledge/formats` — 当前已注册后缀  
- `POST /knowledge/ingest` — 目录入库  
- `POST /knowledge/ingest/upload` — 上传单文件入库  

## 代码入口

- 注册与扫描：`app/rag/parsing/registry.py`
- 编排入库：`app/rag/ingest.py`
- 切块：`app/rag/chunking.py`
