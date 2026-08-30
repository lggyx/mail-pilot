# mail-pilot 设计文档

> 本文档是实现的蓝图：模块结构、数据库 schema、REST API 草案、前端页面清单、视觉基线与合规边界。
> 功能需求以 README 与任务 brief 为准；实现与文档不一致时，以代码实际行为修正本文档。

## 0. 产品定位与合规边界

给自己**拥有同意关系**的联系人列表发邮件的工具。合规内置于产品而非事后补丁：

- 单一发件身份（一个已验证域名或一个已认证邮箱），不做多账号轮换
- 名单只能由用户自己导入（CSV/XLSX/JSON/TXT/粘贴），不提供任何邮箱爬取能力
- 内置退订名单：导入时自动与退订名单求差集，被排除的地址有记录可查
- 遵守渠道限速：发送计划 = 分批 + 限速 + 指数退避重试，不可关闭（只能调参）
- 不实现随机化间隔规避检测；Resend webhook / SMTP 退信事件如实回传并展示
- 「垃圾箱风险体检」只做内容质量分析（触发词、链接、结构、文本比），帮用户把
  合规邮件写得更易送达。**没有任何 API 能直接知道邮件进了垃圾箱**——complained 事件
  + 退信 + AI 内容分析是最接近的可实现组合（详见 README「送达验证的边界」）

## 1. 总体架构

单进程单体（2 核 2G 目标）：FastAPI 同进程挂 APScheduler 定时任务，前端 build 产物由
FastAPI 静态托管，SQLite（WAL 模式）做唯一存储。不上 Redis / 队列 / 独立 worker。

```
┌─────────────────────────── 容器 app (uvicorn 单进程) ───────────────────────────┐
│  FastAPI                                                                       │
│  ├─ /api/*        REST（session cookie 鉴权；/api/webhooks/resend 验签放行）      │
│  ├─ /assets/*     前端 build 静态托管（SPA fallback 到 index.html）              │
│  └─ APScheduler   发送推进器 / IMAP 同步 / 退信扫描 / 重试退避                    │
├────────────────────────────────────────────────────────────────────────────────┤
│  services/                                                                     │
│   importer   名单导入（4 格式+粘贴，去重/校验/退订差集/打标签）                    │
│   renderer   模板渲染（{{var}} 占位、Markdown→HTML、纯文本降级、CID 内嵌图）       │
│   sender     Resend API（httpx）/ SMTP（aiosmtplib）双渠道发送                   │
│   throttle   令牌桶限速器（进程内，批次+每分钟配额）                              │
│   ai_adapter OpenAI 兼容适配层（httpx，非 SDK，/chat/completions + /models）     │
│   ai_tasks   代写/改写/体检/退信归因/摘要/草拟回复（prompt 模板 + JSON 输出）      │
│   imap_sync  IMAP 收件同步（imaplib 线程池执行）+ 退信箱扫描                      │
├────────────────────────────────────────────────────────────────────────────────┤
│  SQLite (WAL)：contacts/tags/templates/campaigns/recipients/events/messages/…  │
└────────────────────────────────────────────────────────────────────────────────┘
        ↑ webhook（Resend 实时回传 delivered/opened/bounced/complained）
        ↑ IMAP（收件箱同步 + 退信箱扫描）   →  Caddy 自动 HTTPS 反代
```

## 2. 目录结构

```
mail-pilot/
├── backend/
│   ├── pyproject.toml            # uv 管理依赖
│   ├── app/
│   │   ├── main.py               # FastAPI 装配：路由/中间件/调度器/静态托管
│   │   ├── config.py             # .env 配置（pydantic-settings）
│   │   ├── db.py                 # engine/session（WAL、外键）
│   │   ├── models.py             # SQLAlchemy 2.x ORM
│   │   ├── schemas.py            # Pydantic 请求/响应
│   │   ├── auth.py               # 登录 + itsdangerous 签名 session cookie
│   │   ├── utils/email_addr.py   # 地址解析/规范化/校验
│   │   ├── routers/
│   │   │   ├── auth.py           # 登录/登出/当前用户
│   │   │   ├── contacts.py       # 联系人/标签/导入/会话聚合
│   │   │   ├── templates.py      # 模板 CRUD
│   │   │   ├── campaigns.py      # 活动计划/确认/暂停/继续/收件人时间线
│   │   │   ├── channels.py       # Resend / IMAP+SMTP 渠道 CRUD/测试
│   │   │   ├── webhooks.py       # Resend webhook（签名验证，免登录）
│   │   │   ├── inbox.py          # IMAP 同步/列表/批量操作/回复
│   │   │   ├── ai.py             # 代写/改写/体检/归因/摘要/草拟回复
│   │   │   ├── uploads.py        # 附件上传/下载
│   │   │   └── settings.py       # AI 配置 CRUD + 常规设置 + 概览统计
│   │   └── services/             # 见「总体架构」
│   └── tests/                    # pytest：导入去重/渲染/状态机/限速器/认证
├── frontend/
│   ├── package.json              # bun 管理
│   ├── vite.config.ts            # dev 代理 /api → 8000；build 出 assets/
│   ├── src/
│   │   ├── lib/                  # api client、hooks（query/快捷键/Toast）、format
│   │   ├── components/           # ui 基件（Button/Card/Badge/Modal/ Skeleton…）
│   │   │   └── editor/           # 三模式编辑器（TipTap 富文本 / Markdown / HTML）
│   │   ├── pages/                # 见「前端页面清单」
│   │   └── main.tsx / App.tsx    # 路由 + 布局 + 守卫
│   └── tests/                    # vitest
└── deploy/
    ├── Dockerfile                # 多阶段：bun 构建前端 → uv 运行后端
    ├── docker-compose.yml        # app + caddy，卷挂数据与 Caddyfile
    ├── Caddyfile.sample
    ├── .env.server.example
    └── DEPLOY.md                 # 2C2G 部署指南（DNS/Resend webhook/备份）
```

## 3. 数据库 schema（SQLite + SQLAlchemy 2.x）

时间戳统一 `datetime`（UTC 存储）；金额/计数用整数。`id` 为自增主键。

| 表 | 字段要点 | 说明 |
|---|---|---|
| `tags` | name unique, color | 标签分组 |
| `contacts` | email unique(规范化小写), name, status, source, note, created_at, last_email_at | status: active / unsubscribed / bounced / complained |
| `contact_tags` | contact_id, tag_id, (unique 联合) | 多对多 |
| `templates` | name, subject, mode(rich/markdown/html), body(当前模式正文), variables(JSON 自动提取), created_at, updated_at | 富文本正文存 HTML；variables 由渲染器自动扫描 |
| `channels` | kind(resend/smtp), name, config(JSON 加密?——明文存本地 SQLite，文件权限保护), is_default, status(unverified/ok/error), last_error, created_at | resend: api_key+from；smtp: host/port/user/password/from + 可选 imap host/port/user/password（M3 收件/退信扫描） |
| `campaigns` | name, subject, mode, body, channel_id, status, batch_size, rate_per_minute, max_retries, plan(JSON), counts(sent/delivered/opened/bounced/complained/failed/skipped), created_at, started_at, finished_at | status: draft/planned/sending/paused/completed/cancelled/failed |
| `campaign_recipients` | campaign_id, contact_id, email, name, status, attempts, next_retry_at, error, provider_message_id, sent_at, delivered_at, opened_at, bounced_at, complained_at | status: pending/sending/sent/delivered/opened/bounced/complained/failed/skipped；(unique campaign_id+email) |
| `recipient_events` | recipient_id, type(sent/delivered/opened/bounced/complained/failed/retry/skipped), detail(JSON), created_at | 追加式时间线 |
| `attachments` | campaign_id(可空=草稿暂存), filename, stored_path, mime, size, cid(可空, 内嵌图), created_at | 发送时 campaign_id 关联；CID 图进 multipart/related |
| `messages` | direction(inbound/outbound), contact_id, channel_id, message_id(unique), in_reply_to, from_email, from_name, to_email, subject, text, html, snippet, folder, is_read, is_archived, received_at, sent_at, raw_headers(JSON) | 收件箱 + 发出的回复同表聚合会话 |
| `ai_configs` | name, base_url, api_key, model, is_active, last_test_at, last_test_ok, created_at | 多配置，激活一个 |
| `app_settings` | key unique, value(JSON) | 常规设置（如默认渠道、每分钟全局上限） |
| `webhook_log` | provider, type, payload(JSON), handled(bool), created_at | 调试与审计 |

**收件人状态机**（事件驱动，append-only）：

```
pending ──发送──> sent ──Resend:email.delivered──> delivered ──opened──> opened
   │                │ ├─ email.bounced ──> bounced        ( complained 可在任意送达态后 )
   │                │ └─ email.complained ─> complained
   └─被退订/重复排除─> skipped
sending/failed ──指数退避重试(next_retry_at)──> 回到 sending（超过 max_retries → failed）
```

## 4. REST API 草案

前缀 `/api`；除 `/auth/login`、`/webhooks/resend` 外全部需要 session cookie。
响应统一 `{data: ...}` 或错误 `{error: {code, message}}`；列表走 `?page=&page_size=&q=`。

```
POST /auth/login {username,password} → Set-Cookie: mp_session
POST /auth/logout                      GET /auth/me

GET/POST /contacts           GET/PUT/DELETE /contacts/{id}
POST /contacts/import        # multipart(file) 或 JSON{text,format}；参数 tag_ids、autocreate_tag
                             # 返回 {added, updated, skipped_duplicates, excluded_unsubscribed, invalid[]}
GET /contacts/{id}/thread    # 与该联系人往来消息(inbox+outbound 合并时间线)
POST /contacts/{id}/status   # 手动改状态（如恢复 active）
GET/POST /tags               PUT/DELETE /tags/{id}

GET/POST /templates          GET/PUT/DELETE /templates/{id}

GET/POST /channels           PUT/DELETE /channels/{id}
POST /channels/{id}/test     # 发测试邮件 → 返回成功/失败与错误详情

GET/POST /campaigns          GET/PUT/DELETE /campaigns/{id}
PUT  /campaigns/{id}/recipients   # 设定收件人（tag 过滤 / 指定 id 列表）→ 预览统计（含将被排除数）
POST /campaigns/{id}/plan    # 生成发送计划（人数/批次/预计耗时/渠道/将被排除名单摘要）
POST /campaigns/{id}/confirm # 确认计划 → status=sending，调度器接管
POST /campaigns/{id}/pause | /resume | /cancel
GET  /campaigns/{id}/recipients?page&status
GET  /campaigns/{id}/recipients/{rid}/events   # 时间线

POST /webhooks/resend        # svix 签名验证（Resend 官方用 svix 头）
GET/POST /uploads            # 上传附件/图片（multipart）；图片可选 embed=true 返回 CID
GET  /uploads/{id}           # 下载/预览（鉴权）

POST /ai/generate  {intent, tone?, mode?}            # 意图 → 主题+正文
POST /ai/rewrite   {subject, body, instruction}      # 一键改写
POST /ai/checkup   {subject, html, text}             # 垃圾箱风险体检（评分+问题+建议）
POST /ai/analyze-bounces {campaign_id}               # 退信/投诉归因 + 生成整改版（供新建活动）
POST /ai/summarize {message_ids[]}                   # 会话摘要
POST /ai/draft-reply {message_ids[], instruction?}   # 草拟回复

GET/POST /inbox           GET /inbox/{id}           POST /inbox/sync
POST /inbox/batch         {ids, action: read|unread|archive|unarchive|tag|summary|delete}
POST /inbox/reply         {message_ids[], subject, body, channel_id}  # 批量回复（聚合到会话）
GET  /contacts/{id}/thread                      # 会话视图数据源

GET/POST/PUT/DELETE /ai-configs      POST /ai-configs/{id}/test   POST /ai-configs/{id}/activate
GET/PUT /settings                    GET  /dashboard/stats        # 概览统计
GET  /health                         # 无鉴权健康检查（容器探针）
```

## 5. 前端页面清单

路由（React Router，懒加载；布局含左侧栏 + 顶栏，j/k 列表导航、c 写信、/ 搜索）：

| 路由 | 页面 | 要点 |
|---|---|---|
| `/login` | 登录 | 单用户账号密码；错误提示 |
| `/` | Dashboard 概览 | 统计卡（联系人/发送/送达率/打开率/退订）、最近活动、送达分布 |
| `/contacts` | 联系人列表 | 搜索/状态筛选/标签筛选；行内快捷操作；j/k 导航 |
| `/contacts/:id` | 联系人详情 | 资料 + 状态时间线 + 往来会话（inbox 聚合）+ AI 摘要 |
| `/contacts/import` | 导入向导 | 拖拽文件（CSV/XLSX/JSON/TXT）或粘贴；预览 → 冲突/退订差集报告 → 完成 |
| `/templates` | 模板列表 | 卡片网格；新建/复制/删除 |
| `/templates/:id` | 模板编辑 | 三模式切换（富文本/Markdown/HTML）；AI 代写/改写；变量提示 |
| `/campaigns` | 活动列表 | 状态徽标 + 进度条 + 计数 |
| `/campaigns/:id` | 活动详情 | 三步：① 编辑收件人/内容/渠道 → ② 发送计划确认 → ③ 进度与逐收件人时间线；暂停/继续/取消；发送后 AI 体检入口 |
| `/inbox` | 收件箱 | 列表（未读/全部/归档）；批量选择：已读/归档/打标/AI 摘要；j/k |
| `/inbox/:id` | 会话视图 | 聚合该联系人往来；AI 草拟回复；批量回复（多选联系人） |
| `/settings` | 设置 | Tab：AI 配置（多组增删改测/激活）、渠道管理（Resend/IMAP+SMTP 测试）、常规 |

视觉基线（抓取 lggyx.vercel.app 得到的 tokens）：近黑底 `#0a0a0a`、卡片 `#161616`、
白色透明度描边（white/8–15%）、暖琥珀强调 `#ffebc8`→`#ffb066` 渐变、成功绿、
圆角 sm–xl（0.25–0.75rem）、过渡 150–300ms cubic-bezier(.22,1,.36,1)、玻璃拟态点缀。
丝滑三件套：路由懒加载 + TanStack Query 乐观更新 + 骨架屏；动效克制（入场 fade-slide、
数字 CountUp、进度条平滑推进），参考 React Bits 的实现思路自研轻量组件。

## 6. 关键技术决策

- **发送推进**：`campaigns.status=sending` 时 APScheduler 每 5s 唤醒推进器：取
  `pending/failed(到重试时间)` 收件人，经令牌桶限速后逐个发送（SMTP 同步调用进线程池）。
  暂停=状态位，继续=重置调度，取消=剩余收件人置 skipped。
- **限速器**：进程内令牌桶（`rate_per_minute`），另有全局最小间隔 1s 防突发；重启后恢复
  （campaigns 状态落库，幂等）。
- **重试**：失败指数退避 2^n 分钟（n=attempts），超过 max_retries 置 failed。
- **Markdown→HTML**：markdown-it-py；纯文本版自动从 HTML 抽取（去标签+压缩空白）。
- **Resend webhook 验签**：svix 库头（`svix-id/svix-timestamp/svix-signature`），密钥来自
  渠道配置；时间戳容差 5 分钟。
- **IMAP**：imaplib 同步 API 在线程池执行；UID 缓存于 messages.message_id 防重复；
  QQ/163 需应用专用密码（文档说明）；退信扫描扫描指定 folder（默认 INBOX 及 bounced）
  匹配 `Delivery Status Notification` 解析原始收件人。
- **AI 适配层**：httpx 直连 `{base_url}/chat/completions`，`Authorization: Bearer`；
  支持流式（SSE 转发）用于编辑器内生成；错误分类（401/429/超时）透出。
- **附件**：本地磁盘 `data/attachments/`（容器卷）；内嵌图生成 CID 并在 HTML 中替换
  `src="{cid:xxx}"`；外链图不动。
- **配置**：全部凭据来自 `.env`（后端）与渠道/AI 配置表（用户在界面录入，存本地 SQLite，
  随数据卷备份）；`.env.example` 提供样例，`.gitignore` 排除 `.env` 与 `data/`。

## 7. 里程碑

- **M1 渠道与发送**：脚手架、认证、渠道 CRUD、名单导入、模板、三模式编辑、批量发送
  （计划→确认→限速推进→暂停/继续）、Resend webhook、时间线。
- **M2 AI 层**：适配器+设置页、代写/改写、发送前体检与整改、附件与内嵌图。
- **M3 收件箱与打磨**：IMAP 同步、联系人聚合视图、批量操作、AI 摘要/草拟回复、
  前端动效与快捷键。
- **交付**：deploy/ 目录 + 《部署指南》。
