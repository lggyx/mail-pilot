/** 设置：AI 配置（多组）/ 渠道管理（Resend + IMAP/SMTP）/ 常规（退订链接）。 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, AIConfig, Channel } from "../lib/api";
import { Badge, Button, Card, Input, Modal, Skeleton } from "../components/ui";
import { toast, toastError } from "../lib/toast";
import { useTitle } from "../lib/hooks";

export default function SettingsPage() {
  useTitle("设置");
  const [tab, setTab] = useState<"ai" | "channels" | "general">("ai");
  const tabs = [
    { key: "ai", label: "AI 配置" },
    { key: "channels", label: "渠道管理" },
    { key: "general", label: "常规" },
  ] as const;

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      <h1 className="text-xl font-semibold text-white">设置</h1>
      <div className="flex gap-1 rounded-lg border border-line bg-card p-1">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 rounded-md px-3 py-2 text-sm transition-all ${
              tab === t.key ? "bg-accent/15 font-medium text-accent" : "text-fog hover:text-neutral-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === "ai" && <AITab />}
      {tab === "channels" && <ChannelsTab />}
      {tab === "general" && <GeneralTab />}
    </div>
  );
}

/* ------------------------------------------------------------ AI 配置 ---- */

function AITab() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<AIConfig | "new" | null>(null);
  const q = useQuery({ queryKey: ["ai-configs"], queryFn: () => api<AIConfig[]>("/api/ai-configs") });

  const activate = useMutation({
    mutationFn: (id: number) => api(`/api/ai-configs/${id}/activate`, { method: "POST" }),
    onSuccess: () => {
      toast("已切换激活配置");
      qc.invalidateQueries({ queryKey: ["ai-configs"] });
    },
    onError: toastError,
  });
  const test = useMutation({
    mutationFn: (id: number) => api<{ ok: boolean; error?: string; models?: string[] }>(`/api/ai-configs/${id}/test`, { method: "POST" }),
    onSuccess: (r, id) => {
      if (r.ok) toast("连接成功");
      else toastError(new Error(r.error || "连接失败"));
      qc.invalidateQueries({ queryKey: ["ai-configs"] });
      return r;
    },
    onError: toastError,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/ai-configs/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["ai-configs"] }),
    onError: toastError,
  });

  return (
    <div className="space-y-3">
      <p className="text-xs text-fog">
        填 base_url + api_key + model 即接入任意 OpenAI 兼容服务（OpenAI / DeepSeek / 智谱 / Kimi / Ollama 本地等）。
        可保存多组并随时切换。
      </p>
      {q.isLoading ? (
        <Skeleton className="h-20" />
      ) : (
        q.data?.map((c) => (
          <Card key={c.id} className="flex items-center gap-3 p-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-medium text-white">{c.name}</span>
                {c.is_active && <span className="rounded bg-ok/15 px-1.5 py-0.5 text-[10px] font-medium text-ok">使用中</span>}
                {c.last_test_ok === true && <span className="text-[10px] text-ok">✓ 已连通</span>}
                {c.last_test_ok === false && <span className="text-[10px] text-bad">✕ 上次测试失败</span>}
              </div>
              <div className="truncate text-xs text-fog">{c.base_url} · {c.model} · key {c.api_key}</div>
            </div>
            {!c.is_active && <Button size="sm" onClick={() => activate.mutate(c.id)}>启用</Button>}
            <Button size="sm" variant="ghost" onClick={() => test.mutate(c.id)} disabled={test.isPending}>测试</Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(c)}>编辑</Button>
            <Button size="sm" variant="ghost" className="hover:text-bad" onClick={() => { if (window.confirm(`删除配置「${c.name}」？`)) remove.mutate(c.id); }}>删除</Button>
          </Card>
        ))
      )}
      <Button variant="primary" onClick={() => setEditing("new")}>＋ 添加 AI 配置</Button>

      <AIConfigModal
        editing={editing}
        onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); qc.invalidateQueries({ queryKey: ["ai-configs"] }); }}
      />
    </div>
  );
}

function AIConfigModal({ editing, onClose, onSaved }: { editing: AIConfig | "new" | null; onClose: () => void; onSaved: () => void }) {
  const isNew = editing === "new";
  const c = isNew ? null : editing;
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");

  // 打开时回填（简单做法：key 变化时重置）
  const key = c ? `edit-${c.id}` : "new";
  const [loadedKey, setLoadedKey] = useState("");
  if (loadedKey !== key) {
    setLoadedKey(key);
    setName(c?.name || "");
    setBaseUrl(c?.base_url || "");
    setApiKey(c?.api_key || "");
    setModel(c?.model || "");
  }

  const save = useMutation({
    mutationFn: () => {
      const payload = { name, base_url: baseUrl, api_key: apiKey, model };
      return isNew
        ? api("/api/ai-configs", { method: "POST", json: payload })
        : api(`/api/ai-configs/${c!.id}`, { method: "PUT", json: payload });
    },
    onSuccess: () => {
      toast("已保存");
      onSaved();
    },
    onError: toastError,
  });

  return (
    <Modal open={editing !== null} onClose={onClose} title={isNew ? "添加 AI 配置" : "编辑 AI 配置"}>
      <div className="space-y-3">
        <LabeledInput label="名称" value={name} onChange={setName} placeholder="如：DeepSeek / 智谱 / 本地 Ollama" />
        <LabeledInput label="Base URL" value={baseUrl} onChange={setBaseUrl} placeholder="https://api.deepseek.com（自动补 /v1）" />
        <LabeledInput label="API Key" value={apiKey} onChange={setApiKey} placeholder="sk-…（编辑时保持 *** 表示不修改）" type="password" />
        <LabeledInput label="Model" value={model} onChange={setModel} placeholder="deepseek-chat / glm-4.6 / llama3 等" />
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button variant="primary" disabled={!name.trim() || !baseUrl.trim() || !model.trim() || save.isPending} onClick={() => save.mutate()}>
            保存
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function LabeledInput({ label, value, onChange, placeholder, type = "text" }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs text-fog">{label}</label>
      <Input type={type} value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
    </div>
  );
}

/* ------------------------------------------------------------ 渠道 ---- */

function ChannelsTab() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<Channel | "new" | null>(null);
  const q = useQuery({ queryKey: ["channels"], queryFn: () => api<Channel[]>("/api/channels") });

  const test = useMutation({
    mutationFn: ({ id, to }: { id: number; to?: string }) =>
      api<{ ok: boolean; error?: string }>(`/api/channels/${id}/test${to ? `?to=${encodeURIComponent(to)}` : ""}`, { method: "POST" }),
    onSuccess: (r) => {
      if (r.ok) toast("渠道正常");
      else toastError(new Error(r.error || "渠道异常"));
      qc.invalidateQueries({ queryKey: ["channels"] });
    },
    onError: toastError,
  });
  const setDefault = useMutation({
    mutationFn: (ch: Channel) => api(`/api/channels/${ch.id}`, { method: "PUT", json: { kind: ch.kind, name: ch.name, config: {}, is_default: true } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["channels"] }),
    onError: toastError,
  });
  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/channels/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["channels"] }),
    onError: toastError,
  });

  return (
    <div className="space-y-3">
      <p className="text-xs text-fog">
        Resend：域名发送 + webhook 实时回传送达状态。SMTP：任意邮箱（QQ/163/Gmail/Outlook/企业邮箱，应用专用密码），
        可同时填 IMAP 用于收件箱同步与退信扫描。
      </p>
      {q.isLoading ? (
        <Skeleton className="h-20" />
      ) : (
        q.data?.map((ch) => (
          <Card key={ch.id} className="flex items-center gap-3 p-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="font-medium text-white">{ch.name}</span>
                <span className="rounded border border-line2 px-1.5 py-0.5 text-[10px] text-fog">
                  {ch.kind === "resend" ? "Resend" : "SMTP/IMAP"}
                </span>
                {ch.is_default && <span className="rounded bg-ok/15 px-1.5 py-0.5 text-[10px] text-ok">默认</span>}
                <Badge value={ch.status} />
              </div>
              <div className="truncate text-xs text-fog">
                {ch.kind === "resend"
                  ? `${(ch.config?.from as string) || ""} · key ${String(ch.config?.api_key || "").slice(0, 8)}…`
                  : `${(ch.config?.smtp as Record<string, unknown>)?.host || ""} · ${(ch.config?.from as string) || ""}`}
                {ch.last_error && <span className="text-bad"> · {ch.last_error}</span>}
              </div>
            </div>
            {!ch.is_default && <Button size="sm" onClick={() => setDefault.mutate(ch)}>设默认</Button>}
            <Button size="sm" variant="ghost" onClick={() => { const to = window.prompt("发测试邮件到（可留空仅测连通）："); if (to !== null) test.mutate({ id: ch.id, to: to || undefined }); }}>测试</Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(ch)}>编辑</Button>
            <Button size="sm" variant="ghost" className="hover:text-bad" onClick={() => { if (window.confirm(`删除渠道「${ch.name}」？`)) remove.mutate(ch.id); }}>删除</Button>
          </Card>
        ))
      )}
      <div className="flex gap-2">
        <Button variant="primary" onClick={() => setEditing("new")}>＋ 添加渠道</Button>
      </div>

      <ChannelModal
        editing={editing}
        onClose={() => setEditing(null)}
        onSaved={() => { setEditing(null); qc.invalidateQueries({ queryKey: ["channels"] }); }}
      />
    </div>
  );
}

function ChannelModal({ editing, onClose, onSaved }: { editing: Channel | "new" | null; onClose: () => void; onSaved: () => void }) {
  const isNew = editing === "new";
  const c = isNew ? null : editing;
  const key = c ? `edit-${c.id}` : "new";
  const [loadedKey, setLoadedKey] = useState("");
  const [kind, setKind] = useState<"resend" | "smtp">("smtp");
  const [name, setName] = useState("");
  const [from, setFrom] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [webhookSecret, setWebhookSecret] = useState("");
  const [smtpHost, setSmtpHost] = useState("");
  const [smtpPort, setSmtpPort] = useState(587);
  const [smtpUser, setSmtpUser] = useState("");
  const [smtpPass, setSmtpPass] = useState("");
  const [imapHost, setImapHost] = useState("");
  const [imapPort, setImapPort] = useState(993);
  const [imapUser, setImapUser] = useState("");
  const [imapPass, setImapPass] = useState("");
  const [bounceFolder, setBounceFolder] = useState("INBOX");

  if (loadedKey !== key) {
    setLoadedKey(key);
    const cfg = c?.config || {};
    const smtp = (cfg.smtp as Record<string, unknown>) || {};
    const imap = (cfg.imap as Record<string, unknown>) || {};
    setKind(c?.kind || "smtp");
    setName(c?.name || "");
    setFrom((cfg.from as string) || "");
    setApiKey((cfg.api_key as string) || "");
    setWebhookSecret((cfg.webhook_secret as string) || "");
    setSmtpHost((smtp.host as string) || "");
    setSmtpPort(Number(smtp.port || 587));
    setSmtpUser((smtp.user as string) || "");
    setSmtpPass((smtp.password as string) || "");
    setImapHost((imap.host as string) || "");
    setImapPort(Number(imap.port || 993));
    setImapUser((imap.user as string) || "");
    setImapPass((imap.password as string) || "");
    setBounceFolder((imap.bounce_folder as string) || "INBOX");
  }

  const save = useMutation({
    mutationFn: () => {
      const config: Record<string, unknown> = { from };
      if (kind === "resend") {
        config.api_key = apiKey;
        if (webhookSecret) config.webhook_secret = webhookSecret;
      } else {
        config.smtp = { host: smtpHost, port: smtpPort, user: smtpUser, password: smtpPass };
        if (imapHost) {
          config.imap = { host: imapHost, port: imapPort, user: imapUser || smtpUser, password: imapPass || smtpPass, bounce_folder: bounceFolder };
        }
      }
      const payload = { kind, name, config, is_default: false };
      return isNew
        ? api("/api/channels", { method: "POST", json: payload })
        : api(`/api/channels/${c!.id}`, { method: "PUT", json: payload });
    },
    onSuccess: () => {
      toast("已保存");
      onSaved();
    },
    onError: toastError,
  });

  return (
    <Modal open={editing !== null} onClose={onClose} title={isNew ? "添加渠道" : "编辑渠道"} wide>
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs text-fog">渠道类型</label>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as "resend" | "smtp")}
              disabled={!isNew}
              className="w-full rounded-lg border border-line2 bg-black/30 px-3 py-2 text-sm outline-none focus:border-accent/60"
            >
              <option value="smtp">通用邮箱（SMTP / IMAP）</option>
              <option value="resend">Resend（域名发送）</option>
            </select>
          </div>
          <LabeledInput label="名称" value={name} onChange={setName} placeholder="如：QQ 邮箱 / 公司域名" />
        </div>
        <LabeledInput label="发件人（From）" value={from} onChange={setFrom} placeholder="名字 <you@domain.com> 或 you@domain.com" />

        {kind === "resend" ? (
          <>
            <LabeledInput label="Resend API Key" value={apiKey} onChange={setApiKey} placeholder="re_…（编辑时保持 *** 表示不修改）" type="password" />
            <LabeledInput label="Webhook 签名密钥（可选）" value={webhookSecret} onChange={setWebhookSecret}
              placeholder="whsec_…（Resend 控制台创建 webhook 时提供，用于验签）" />
            <p className="text-xs text-fog/70">提示：在 Resend 控制台把 webhook 地址填为 https://你的域名/api/webhooks/resend</p>
          </>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-4">
              <LabeledInput label="SMTP 主机" value={smtpHost} onChange={setSmtpHost} placeholder="smtp.qq.com" />
              <LabeledInput label="端口" value={String(smtpPort)} onChange={(v) => setSmtpPort(Number(v) || 587)} placeholder="587" />
              <LabeledInput label="账号" value={smtpUser} onChange={setSmtpUser} placeholder="you@qq.com" />
              <LabeledInput label="密码/授权码" value={smtpPass} onChange={setSmtpPass} type="password" placeholder="应用专用密码" />
            </div>
            <div className="mt-2 rounded-lg border border-line p-3">
              <p className="mb-2 text-xs font-medium text-fog">IMAP（可选：收件箱同步 + 退信扫描）</p>
              <div className="grid gap-3 sm:grid-cols-4">
                <LabeledInput label="IMAP 主机" value={imapHost} onChange={setImapHost} placeholder="imap.qq.com" />
                <LabeledInput label="端口" value={String(imapPort)} onChange={(v) => setImapPort(Number(v) || 993)} placeholder="993" />
                <LabeledInput label="账号" value={imapUser} onChange={setImapUser} placeholder="默认同 SMTP" />
                <LabeledInput label="密码" value={imapPass} onChange={setImapPass} type="password" placeholder="默认同 SMTP" />
              </div>
              <div className="mt-2">
                <LabeledInput label="退信扫描文件夹" value={bounceFolder} onChange={setBounceFolder} placeholder="INBOX" />
              </div>
            </div>
            <p className="text-xs text-fog/70">QQ/163 等需在邮箱设置中开启 IMAP/SMTP 并使用「应用专用密码」（授权码）。</p>
          </>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>取消</Button>
          <Button variant="primary" disabled={!name.trim() || save.isPending} onClick={() => save.mutate()}>保存</Button>
        </div>
      </div>
    </Modal>
  );
}

/* ------------------------------------------------------------ 常规 ---- */

function GeneralTab() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<Record<string, { url?: string }>>("/api/settings") });
  const [url, setUrl] = useState("");
  const [loaded, setLoaded] = useState(false);
  if (settings.data && !loaded) {
    setLoaded(true);
    setUrl(settings.data.list_unsubscribe_url?.url || "");
  }

  const save = useMutation({
    mutationFn: () => api("/api/settings", { method: "PUT", json: { key: "list_unsubscribe_url", value: { url } } }),
    onSuccess: () => toast("已保存"),
    onError: toastError,
  });

  return (
    <Card className="space-y-3 p-5">
      <div>
        <label className="mb-1 block text-xs text-fog">退订链接模板（含 {'{email}'} 占位符；留空则不加退订头）</label>
        <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://your-domain.com/unsubscribe?email={email}" />
      </div>
      <p className="text-xs text-fog/70">
        配置后批量发送会自动附加 List-Unsubscribe / List-Unsubscribe-Post 头（RFC 8058 一键退订）。
        建议同时在邮件页脚写明退订方式。
      </p>
      <div className="flex justify-end">
        <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending}>保存</Button>
      </div>
    </Card>
  );
}
