# mail-pilot 部署指南（2 核 2G 服务器）

目标环境：自有 Linux 服务器（Debian/Ubuntu 均可），2 核 CPU / 2G 内存，已安装 Docker 与
Docker Compose v2。架构：**app**（FastAPI 单进程 + SQLite，静态托管前端产物）+ **Caddy**
（自动 HTTPS 反代）。无 Redis、无队列、无独立 worker，一台服务器跑完全部。

## 0. 前置条件

- 一个域名（如 `mail.example.com`），DNS **A 记录**指向服务器公网 IP
  - 若用国内服务器：域名需完成备案；80/443 端口在云安全组放行
- 服务器装好 Docker：`curl -fsSL https://get.docker.com | sh`
- 想用 Resend 渠道：注册 [resend.com](https://resend.com)，添加并验证发送域名（改 DNS：
  SPF/DKIM/DMARC 记录，Resend 控制台会给出具体值）

## 1. 上传代码

```bash
git clone https://github.com/lggyx/mail-pilot.git /opt/mail-pilot
cd /opt/mail-pilot/deploy
```

（私有仓库首次 clone 需要 token，或在本机打包上传。）

## 2. 配置环境

```bash
cp .env.server.example .env.server
cp Caddyfile.sample Caddyfile
# 1) 编辑 .env.server：设置强 SECRET_KEY 与账号密码
openssl rand -hex 32    # 把输出填到 SECRET_KEY
# 2) 编辑 Caddyfile：把 mail.example.com 换成你的域名
```

## 3. 构建并启动

```bash
docker compose up -d --build
docker compose logs -f app     # 看到 "Application startup complete" 即可
```

验证：浏览器打开 `https://你的域名` → 登录页 → 用 .env.server 里的账号密码登录。
Caddy 首次启动会自动申请 Let's Encrypt 证书（需要 80/443 可达）。

## 4. 渠道配置（登录后在「设置 → 渠道管理」）

### Resend（推荐：送达状态实时回传）
1. Resend 控制台 → API Keys → 创建 `re_...` 密钥
2. 渠道管理 → 添加渠道 → 类型 Resend → 填 API Key 与发件人（如 `hi@你的域名`）→ 测试
3. **Webhook（送达验证的关键）**：Resend 控制台 → Webhooks → Add Endpoint
   - URL 填：`https://你的域名/api/webhooks/resend`
   - 订阅事件：`email.sent` / `email.delivered` / `email.bounced` / `email.complained` / `email.opened`
   - 创建后得到 Signing Secret（`whsec_...`），回到 mail-pilot 编辑该渠道，填入
     「Webhook 签名密钥」保存 —— 之后所有事件都验签入库

### 通用邮箱（IMAP/SMTP）
1. 邮箱设置里开启 IMAP/SMTP 服务，生成**应用专用密码**（QQ/163 叫「授权码」；Gmail 需应用密码）
2. 渠道管理 → 添加渠道 → 类型通用邮箱 → 填 SMTP 主机/端口（465 或 587）与账号、授权码
3. 同一表单填写 IMAP 信息（QQ：`imap.qq.com:993`；163：`imap.163.com:993`）——
   用于收件箱同步与退信扫描
4. 测试通过后，在收件箱页点「同步 IMAP」验证收信；调度器默认每 30 分钟自动同步

## 5. AI 配置（「设置 → AI 配置」）

任选一家 OpenAI 兼容服务，填三项即可：

| 服务 | Base URL | Model 示例 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| 智谱 | `https://open.bigmodel.cn/api/paas/v4` | `glm-4.6` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Ollama 本地（同机） | `http://172.17.0.1:11434` | `llama3` 等 |

保存后点「测试」验证连通，再点「启用」。

## 6. 例行维护

```bash
# 备份（SQLite + 附件都在 app-data 卷里）
docker run --rm -v mail-pilot_deploy_app-data:/data -v $(pwd):/backup alpine \
    tar czf /backup/mailpilot-backup-$(date +%F).tar.gz -C /data .
# 建议加入 crontab 每日备份，并异地保留一份

# 更新版本
cd /opt/mail-pilot && git pull && cd deploy && docker compose up -d --build

# 查看发送调度日志
docker compose logs -f app | grep -i campaign
```

## 7. 2G 内存调优建议

- compose 已限制 app 内存 1536M，Caddy 极轻
- 若内存吃紧：`docker compose down && free -h` 确认；可加 2G swap 兜底：
  `fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile`
- SQLite 已开 WAL 模式，名单规模在数万级内没有压力；导入单文件建议 ≤ 20MB（程序已限制）

## 8. 安全清单（公网必做）

- [ ] 改掉 .env.server 默认账号密码（强密码）
- [ ] SECRET_KEY 用 openssl 生成的随机值
- [ ] Caddy 强制 HTTPS（默认行为，勿改回 80 直连）
- [ ] 定期备份 app-data 卷
- [ ] 云安全组只放行 22/80/443
