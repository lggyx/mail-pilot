# 更新日志

本项目的所有重要变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.1.0] - 2026-08-31

首个可用版本：从零实现的 AI 邮件工作台（M1/M2/M3 三个里程碑同期交付）。

### M1 渠道与发送
- 单用户登录（.env 账号密码 + 签名 session cookie），全部 API 鉴权
- 渠道管理：Resend（HTTP API）与通用邮箱 IMAP/SMTP 并存，可存多渠道、设默认、连通性测试（可发测试邮件）
- 名单导入：CSV / XLSX / JSON / TXT（每行一个邮箱）/ 富文本粘贴；自动去重、格式校验、
  与退订/退信/投诉名单求差集、标签分组；导入报告含无效行明细
- 模板：三种编辑模式（TipTap 富文本 / Markdown / HTML 源码）即时切换，`{{var}}` 变量自动提取
- 批量发送：campaign 概念；发送计划（人数/批次/限速/预计耗时/渠道）→ 用户确认 →
  调度器接管（APScheduler 每 5s 推进）；令牌桶限速 + 全局最小间隔；失败指数退避重试；
  暂停 / 继续 / 取消；重启后活动状态恢复
- 送达追踪：逐收件人状态机 pending → sent → delivered → opened / bounced / complained，
  追加式事件时间线；Resend webhook 实时回传（svix 验签，无 secret 时开发模式放行）；
  bounced/complained 自动回写联系人状态
- 合规内置：List-Unsubscribe 头（可配退订链接模板）、单一发件身份、无任何规避检测能力

### M2 AI 层
- OpenAI 兼容适配层（httpx 自研薄封装，不绑 SDK）：base_url + api_key + model 即接入
  OpenAI / DeepSeek / 智谱 / Kimi / Ollama 本地等；设置页可存多组配置、切换激活、连通测试
- AI 代写（意图 → 主题+正文）、一键改写（按指令/按体检建议）
- 垃圾箱风险体检（发送前）：本地确定性规则（触发词/链接健康度/纯文本比/图片占比/大写咆哮/退订说明）
  + AI 复核合并输出 0-100 分与整改建议；AI 不可用时自动降级为纯本地规则
- 发送后归因：用 bounced/complained 事件定位问题邮件，AI 分析原因并生成整改版（自动排除问题地址）
- 附件上传（≤20MB 本地存储）；图片支持内嵌（CID，自动生成引用代码）与外链

### M3 收件箱与打磨
- IMAP 同步任意平台邮箱（QQ/163/Gmail/Outlook/企业邮箱，应用专用密码）；message_id 去重；
  发件人自动聚合为联系人
- 联系人聚合会话视图（往来邮件合并时间线）
- 批量操作：批量已读/未读/归档/删除；批量回复（按发件人去重、自动跳过退订地址、走所选渠道、
  回写会话）
- AI 会话摘要、AI 草拟回复
- 退信箱扫描：解析 DSN（Final-Recipient/Action），硬退信回写活动时间线与联系人状态
- 前端：视觉基线取自 lggyx.vercel.app 设计 tokens（暗色 + 暖琥珀强调）；路由懒加载、
  TanStack Query 缓存与乐观刷新、骨架屏、Toast；快捷键 j/k 列表导航、c 写信、
  g+字母跳页、/ 搜索；CountUp 数字滚动、卡片 hover 微抬、分步入场动效（克制）

### 部署
- Docker Compose：app（uv + FastAPI 单进程，静态托管前端 build 产物）+ Caddy（自动 HTTPS）
- 2 核 2G 目标：SQLite（WAL）单库单进程，无 Redis/队列/独立 worker
- 《部署指南》：域名 DNS、Resend webhook 配置、.env.server 样例、备份建议

### 测试
- 后端 pytest 37 例：导入去重/多格式解析、模板渲染、状态机、限速器、认证、API 冒烟、
  发送推进/重试退避、webhook 验签 —— 全绿
- 前端 vitest 12 例：格式化、API 客户端信封解包/错误处理 —— 全绿
