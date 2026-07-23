# FitPilot 演示清单

账号（`fitpilot seed-demo`）：

- 邮箱：`demo@fitpilot.local`
- 密码：`demo123456`

## 启动

```bash
# 依赖：Postgres / Redis / Qdrant / Ollama（按本地 Compose）
cd backend
uv run python main.py migrate
uv run python main.py seed-demo
uv run python main.py knowledge-ingest --incremental   # 可选
uv run python main.py api
# 前端
cd frontend && npm run dev
```

## 推荐流程（约 10 分钟）

1. **登录** demo 账号，打开档案确认目标/体重已填充  
2. **今日记录**：可见近两周训练/饮食种子数据  
3. **知识问答**：如「减脂期蛋白质怎么安排？」→ 展开 RAG 证据面板看引用  
4. **复杂调整**：发送「根据我最近两周的训练记录调整饮食和训练」  
5. **审批面板**：查看 Diff、数据依据、风险提示 → 批准  
6. **计划页**：确认新版本；可选回滚上一版本  
7. **记忆（可选）**：`POST /memories` 提出偏好 → `confirm` 写回档案  

## 验收看点

| 看点 | 体现能力 |
|------|----------|
| 执行轨迹时间线 | Agent 多步工具调用 |
| 证据面板 | RAG + Evidence Gate + Citation |
| 审批 Diff / 依据 | Human-in-the-loop + 确定性计划 |
| 断线 SSE 续传 | 事件持久化 |
| seed-demo | 一键可演示数据 |
