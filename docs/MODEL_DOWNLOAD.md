# FitPilot 模型手动下载说明

本项目需要三类权重：**Ollama 对话模型**、**Embedding**、**Reranker**。  
请在本机网络/代理环境就绪后自行下载，下载完成前可用 `RAG_OFFLINE=1` 先联调业务流（Dense 走哈希向量，BM25/Agent 仍可用）。

## 1. Ollama 对话模型（按环节分模型，省显存）

6GB 显存推荐 **分角色** 使用小参数模型，避免默认加载 7B：

```powershell
# 必装：RAG 生成 + 裁判/辅助
ollama pull qwen2.5:1.5b
ollama pull qwen2.5:0.5b
# 可选：质量优先 RAG（同时请设 EMBEDDING_DEVICE=cpu）
# ollama pull qwen3.5:4b
# 不建议默认：ollama pull qwen2.5:7b
ollama list
```

| 环节 | `.env` | 推荐 |
|------|--------|------|
| RAG 问答 | `OLLAMA_MODEL_RAG` | `qwen2.5:1.5b`（或 `qwen3.5:4b`） |
| 评估裁判 | `OLLAMA_MODEL_JUDGE` | `qwen2.5:0.5b` |
| 查询改写 | `OLLAMA_MODEL_REWRITE` | `qwen2.5:0.5b`（需 `OLLAMA_USE_LLM_REWRITE=true`） |
| 意图辅助 | `OLLAMA_MODEL_CLASSIFY` | `qwen2.5:0.5b`（需 `OLLAMA_USE_LLM_CLASSIFY=true`） |

并建议：

```env
OLLAMA_KEEP_ALIVE=30s
EMBEDDING_DEVICE=cpu
```

确认服务：

```powershell
curl.exe http://127.0.0.1:11434/api/tags
```

## 2. Embedding：`BAAI/bge-small-zh-v1.5`

在已激活的后端 venv 中执行（任选一种）。

### 方式 A：HuggingFace 官方（需可访问 huggingface.co）

```powershell
cd D:\FitPilot\backend
.\.venv\Scripts\Activate.ps1
$env:HF_HUB_DISABLE_TELEMETRY="1"
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5'); print('embedding ok')"
```

### 方式 B：国内镜像

```powershell
cd D:\FitPilot\backend
.\.venv\Scripts\Activate.ps1
$env:HF_ENDPOINT="https://hf-mirror.com"
$env:HF_HUB_DISABLE_TELEMETRY="1"
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5'); print('embedding ok')"
```

### 方式 C：huggingface-cli 指定缓存目录

```powershell
cd D:\FitPilot\backend
.\.venv\Scripts\Activate.ps1
pip install -U huggingface_hub
$env:HF_ENDPOINT="https://hf-mirror.com"
huggingface-cli download BAAI/bge-small-zh-v1.5 --local-dir D:\models\bge-small-zh-v1.5
```

若用本地目录，把 `.env` 改为：

```env
EMBEDDING_MODEL=D:/models/bge-small-zh-v1.5
```

## 3. Reranker：推荐放到本仓库 `models/`

本仓库默认使用 **本项目内** `D:\FitPilot\models\bge-reranker-large`（真实目录，非联接其他仓库）。也可下载 base 版以节省空间。

### 推荐：下载到项目 models 目录

```powershell
cd D:\FitPilot
$env:HF_ENDPOINT="https://hf-mirror.com"
# large（与 .env 默认 RERANKER_MODEL 一致）
python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-reranker-large', local_dir=r'D:\FitPilot\models\bge-reranker-large')"
# 或 base（更小）
# python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-reranker-base', local_dir=r'D:\FitPilot\models\bge-reranker-base')"
```

`.env`：

```env
RERANKER_MODEL=D:/FitPilot/models/bge-reranker-large
```

### 备选：ModelScope / 外部目录

> CrossEncoder 偶发直连失败时，可用 ModelScope 或 huggingface-cli 落到任意本地目录后改 `.env`。

#### ModelScope（国内一般更稳）

```powershell
cd D:\FitPilot\backend
.\.venv\Scripts\Activate.ps1
pip install -U modelscope
python -c "from modelscope import snapshot_download; print(snapshot_download('BAAI/bge-reranker-base', cache_dir=r'D:\models'))"
```

命令会打印本地路径（通常类似 `D:\models\BAAI\bge-reranker-base`）。验证：

```powershell
python -c "from sentence_transformers import CrossEncoder; CrossEncoder(r'D:\models\BAAI\bge-reranker-base'); print('reranker ok')"
```

`.env`：

```env
RERANKER_MODEL=D:/models/BAAI/bge-reranker-base
```

### 备选：huggingface-cli + 镜像

```powershell
cd D:\FitPilot\backend
.\.venv\Scripts\Activate.ps1
pip install -U "huggingface_hub[cli]"
$env:HF_ENDPOINT="https://hf-mirror.com"
huggingface-cli download BAAI/bge-reranker-base --local-dir D:\models\bge-reranker-base
python -c "from sentence_transformers import CrossEncoder; CrossEncoder(r'D:\models\bge-reranker-base'); print('reranker ok')"
```

`.env`：

```env
RERANKER_MODEL=D:/models/bge-reranker-base
```

### 备选：浏览器手动下载

打开 https://modelscope.cn/models/BAAI/bge-reranker-base ，把整包文件下到 `D:\models\bge-reranker-base`，再把 `.env` 的 `RERANKER_MODEL` 指过去。

## 4. 下载完成后入库知识库

确认 `.env` 中 **不要** 设置 `RAG_OFFLINE=1`，设备按显存选择：

```env
EMBEDDING_DEVICE=cuda
RERANKER_DEVICE=cuda
# 显存紧张可改为 cpu，并与 Ollama 错峰
```

```powershell
cd D:\FitPilot
$env:PYTHONPATH="D:\FitPilot\backend"
$env:NO_PROXY="127.0.0.1,localhost"
.\backend\.venv\Scripts\python.exe scripts\ingest_kb.py
```

## 5. 下载前的临时联调（可选）

```powershell
$env:RAG_OFFLINE="1"
$env:PYTHONPATH="D:\FitPilot\backend"
.\backend\.venv\Scripts\python.exe scripts\ingest_kb.py
```

说明：离线入库 Dense 向量为哈希占位，检索质量依赖 BM25；装好真实 Embedding/Reranker 后请重新 `ingest_kb.py`。
