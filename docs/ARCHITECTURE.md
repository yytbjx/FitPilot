# FitPilot 架构概览

```mermaid
flowchart TB
  subgraph Client
    Vue[Vue3 Frontend]
  end

  subgraph API["FastAPI Interface"]
    Auth[Auth API]
    Biz[Business API]
    AgentAPI[Agent Task / SSE]
    MemAPI[Memories API]
  end

  subgraph App["Application Layer"]
    UC[Agent / Plans / Memories Use Cases]
  end

  subgraph Runtime["Agent Runtime"]
    Router[Structured Router]
    Main[Main Graph]
    SG[Domain Subgraphs]
    PEV[Planner-Executor-Validator]
    Tools[Tool Registry]
  end

  subgraph RAG["RAG Service"]
    QU[Query Understanding]
    RP[RetrievalPlan]
    Chunk[Doc-type Chunking]
    Gate[Evidence Gate]
    Cite[Citation Mapping]
  end

  subgraph Infra["Infrastructure"]
    PG[(PostgreSQL)]
    Redis[(Redis Streams)]
    Qdrant[(Qdrant)]
    BM25[BM25]
    Ollama[Ollama]
  end

  Vue --> Auth & Biz & AgentAPI & MemAPI
  AgentAPI --> UC
  UC --> Runtime
  UC --> RAG
  Runtime --> Tools
  Tools --> PG
  RAG --> Qdrant & BM25 & Ollama
  AgentAPI --> Redis
  Runtime --> PG
```

## 原则

- API 不直接跑复杂 Agent；写操作经 Application + 审批
- Agent 经 Tool Registry / Repository，不直接散落 ORM
- RAG 提供可定位证据；低证据拒答
- 任务状态与 SSE 事件以 Postgres 为权威源

## 关键路径

| 能力 | 路径 |
|------|------|
| 主图 | `backend/app/graphs/fitness_graph.py` |
| 子图 | `backend/app/agents/workflows/graphs/` |
| 用例 | `backend/app/application/` |
| 持久化 | `backend/app/infrastructure/persistence/` |
| 知识生命周期 | `backend/app/rag/knowledge_lifecycle.py` |
