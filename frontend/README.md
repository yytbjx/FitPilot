# FitPilot 前端

`web` = Web 前端（Vite 开发服），与后端 `api` 命令区分。

## 短命令启动

```powershell
pnpm install
pnpm start          # 推荐：等同 vite 开发服
# 或
pnpm web
pnpm dev
```

浏览器：http://127.0.0.1:5173

仓库根目录（推荐）：

```powershell
python main.py web
# ui / dev 为 web 别名
```

API 基址见 `.env`：`VITE_API_BASE=http://127.0.0.1:8000/api/v1`
