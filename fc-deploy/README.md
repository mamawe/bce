# BCE 阿里云函数计算部署包（无持久化版）

## 文件结构

```
fc-deploy/
├── bootstrap                # 自定义运行时启动脚本
├── template.yml             # Serverless Devs 部署配置
├── README.md                # 本文件
├── src/
│   ├── server.py            # 自定义运行时入口（复制 DB + 启动 uvicorn）
│   ├── bce.db               # 预构建的 SQLite 数据库
│   └── requirements.txt     # Python 依赖
├── scripts/
│   └── deploy.sh            # 一键部署
└── .env.example             # 环境变量模板（可选）
```

## 部署步骤

### 第 1 步：阿里云准备

1. 注册阿里云账号（实名认证）
2. 开通「函数计算 FC」（无需 OSS）

### 第 2 步：安装工具

```bash
npm install -g @serverless-devs/s
s --version
```

### 第 3 步：配置阿里云凭证

```bash
s config add
# 输入你的 AccessKey ID 和 AccessKey Secret
```

### 第 4 步：配置部署参数

编辑 `template.yml`：
- `LLM_API_KEY`: 智谱 API Key
- `BCE_ALLOWED_ORIGINS`: 前端域名（Vercel URL）

### 第 5 步：部署

```bash
cd fc-deploy
cp ../backend/bce.db src/bce.db   # 同步最新数据库
bash scripts/deploy.sh
```

部署成功后会输出 API 公网 URL，类似：
`https://bce-service-bce-api-cn-hangzhou-xxx.fcapp.run`

### 第 6 步：连接前端

Vercel 环境变量设置：
```
VITE_API_BASE_URL=https://你的fc地址
```

## 费用（免费额度内）

| 项 | 用量 | 费用 |
|----|------|------|
| 函数调用 | ~1,500次/月 | 免费 |
| 执行时间 | ~8GB-秒/月 | 免费 |
| 流量 | ~0.1GB/月 | ¥0.08 |
| 代码存储 | ~1MB | 免费 |
| **合计** | | **≈ ¥0.1/月** |

## 工作原理

```
冷启动 (约 500ms)
  ↓
bootstrap → python src/server.py
  ↓
server.py 复制 bce.db → /tmp/bce.db
  ↓
启动 uvicorn (FastAPI) 监听 :9000
  ↓
接收 HTTP 请求 → 查询 /tmp/bce.db
  ↓
容器回收 → /tmp 丢弃（数据不丢失，下次冷启动重新复制）
```

## 注意事项

- **每次部署前**：确保 `src/bce.db` 是最新版本（从 `backend/bce.db` 复制）
- **数据库大小上限**：`/tmp` 目录 512MB，当前数据库约 700KB
- **冷启动延迟**：约 500ms（仅首次请求有延迟）
- **响应速度**：后续请求 3-8 秒（含 LLM 调用）
- **无数据持久化**：容器回收后 /tmp 丢失，无需担心数据一致性
