# mail-pilot

AI 邮件工作台：给自己**拥有同意关系**的联系人列表发邮件的工具。名单导入、AI 代写与体检、
批量发送、送达追踪、收件箱批量处理。

![status](https://img.shields.io/badge/status-v0.1.0-orange)

## 功能一览

- **多格式名单导入**：CSV / XLSX / JSON / TXT / 粘贴，自动去重、格式校验、与退订名单求差、标签分组
- **三种编辑模式**：TipTap 富文本（所见即所得）/ Markdown 源码 / HTML 源码，即时切换
- **AI 助手**（OpenAI 兼容：OpenAI / DeepSeek / 智谱 / Kimi / Ollama 本地……）：
  - 代写：一句话意图 → 主题 + 正文（支持 `{{name}}` 变量）
  - 改写：按指令或按体检建议一键整改
  - 垃圾箱风险体检：本地规则 + AI 复核，输出 0-100 分与整改建议
  - 收件箱：会话摘要、草拟回复
  - 发送后归因：退信/被标垃圾 → 分析原因 → 生成整改版
- **批量发送**：发送计划（人数/批次/限速/渠道）需确认；分批 + 限速 + 指数退避重试；
  暂停/继续/取消；campaign 逐收件人状态时间线
- **送达验证**：sent → delivered → opened / bounced / complained；Resend webhook 实时回传；
  SMTP 渠道扫退信箱解析 DSN
- **收件箱**：IMAP 同步任意平台邮箱，联系人聚合会话，批量已读/归档/删除、批量 AI 回复
- **双渠道**：Resend（域名 + webhook）与通用 SMTP/IMAP 邮箱并存，发送时可选择
- **丝滑前端**：暗色 + 暖琥珀视觉、路由懒加载、骨架屏、乐观刷新、快捷键（j/k、c、g+字母、/）

## 送达验证的边界（请务必了解）

**没有任何 API 能直接知道"邮件进了垃圾箱"。** mail-pilot 采用最接近的可实现组合：

1. **bounced（拒收）事件**：地址不存在/被拒——硬信号
2. **complained（被标垃圾）事件**：收件人在邮箱客户端点了"举报垃圾邮件"——最接近"进垃圾箱"的信号，
   但只在用户主动举报时产生
3. **AI 内容分析**：对触发词、链接健康度、结构、纯文本比做体检，提前降低风险

Resend 的 delivered/opened 由 webhook 实时回传；SMTP 渠道通过扫描退信箱（DSN 解析）获得退信信号。

## 合规原则（产品内建，不可绕过）

- 单一发件身份；不做多账号轮换、不做随机化间隔规避检测、不提供任何邮箱爬取能力
- 名单只能由用户导入，导入时自动排除退订/退信/被标垃圾地址
- 发送强制限速（每分钟配额 + 批次间隔），List-Unsubscribe 一键退订头可配置
- 请只向**有同意关系**的联系人发送（自己的订阅者、客户等），并遵守目标地区的反垃圾邮件法规

## 快速开始（开发）

后端（Python 3.12 + uv）：

```bash
cd backend
uv sync
cp ../.env.example .env          # 修改 SECRET_KEY / APP_USERNAME / APP_PASSWORD
uv run pytest                    # 全部测试
uv run uvicorn app.main:app --reload --port 8000
```

前端（bun）：

```bash
cd frontend
bun install
bun run dev                      # http://localhost:5173，/api 代理到 8000
bun run test                     # vitest
bun run build                    # 产物 dist/，由 FastAPI 静态托管
```

生产部署见 [deploy/DEPLOY.md](deploy/DEPLOY.md)（Docker Compose + Caddy，2 核 2G 服务器）。

## 目录结构

```
backend/    FastAPI + SQLAlchemy 2.x + SQLite（WAL）+ APScheduler，单进程
frontend/   Vite + React + TS + Tailwind 4 + TipTap + TanStack Query（bun 管理）
deploy/     Dockerfile / docker-compose.yml / Caddyfile 样例 / .env.server 样例
docs/       DESIGN.md（架构/schema/API/页面清单）
```

细节见 [docs/DESIGN.md](docs/DESIGN.md)；变更历史见 [CHANGELOG.md](CHANGELOG.md)。

## 凭据与安全

- 所有凭据只从 `.env` 读（`.env.example` 为样例，`.gitignore` 排除 `.env`）
- 渠道 API key / AI key 在界面录入，存本地 SQLite（随数据卷保存，注意备份与权限）
- 公网部署必须改掉默认账号密码与 SECRET_KEY；Caddy 自动 HTTPS
