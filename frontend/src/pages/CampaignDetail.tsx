/** 活动详情：三步流 —— ① 内容与收件人 → ② 发送计划确认 → ③ 进度与逐收件人时间线。
 *  支持暂停/继续/取消、附件与内嵌图、发送前体检、发送后退信归因。 */

import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Campaign, CampaignPlan, Channel, CheckupResult, Recipient, RecipientEvent, Template, upload } from "../lib/api";
import { Badge, Button, Card, Empty, Input, Modal, Select, Skeleton, STATUS_LABELS, Textarea } from "../components/ui";
import { Editor3Mode, ModeSwitch, EditorMode } from "../components/editor/Editor3Mode";
import { CheckupPanel } from "./TemplateEditor";
import { fmtBytes, fmtDateTime, fmtNum } from "../lib/format";
import { toast, toastError } from "../lib/toast";
import { useTitle } from "../lib/hooks";

interface RecipientRow { items: Recipient[]; total: number; counts: Record<string, number> }
interface AttachInfo { id: number; filename: string; mime: string; size: number; cid: string | null }
interface BounceAnalysisResult {
  analysis: string; causes: string[]; revised_subject: string; revised_body: string;
  excluded_emails: string[]; bounced_count: number; complained_count: number;
}

export default function CampaignDetailPage() {
  const { id } = useParams();
  const isNew = !id || id === "new";
  const navigate = useNavigate();
  const qc = useQueryClient();
  useTitle(isNew ? "新建活动" : "活动详情");

  const cp = useQuery({
    queryKey: ["campaign", id],
    queryFn: () => api<Campaign>(`/api/campaigns/${id}`),
    enabled: !isNew,
    refetchInterval: (query) => (query.state.data?.status === "sending" ? 3000 : false),
  });
  const channels = useQuery({ queryKey: ["channels"], queryFn: () => api<Channel[]>("/api/channels") });
  const templates = useQuery({ queryKey: ["templates"], queryFn: () => api<Template[]>("/api/templates") });

  const [statusFilter, setStatusFilter] = useState("");
  const recipients = useQuery({
    queryKey: ["campaign", id, "recipients", statusFilter],
    queryFn: () => api<RecipientRow>(`/api/campaigns/${id}/recipients?page=1&page_size=100&status=${statusFilter}`),
    enabled: !isNew,
    refetchInterval: (query) => (query.state.data?.counts?.pending ? 5000 : false),
  });

  if (!isNew && cp.isLoading) {
    return <div className="space-y-4 p-6"><Skeleton className="h-8 w-56" /><Skeleton className="h-72" /></div>;
  }
  if (!isNew && !cp.data) return <Empty text="活动不存在" />;

  const c = cp.data;

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-white">{isNew ? "新建活动" : c!.name}</h1>
          {!isNew && <Badge value={c!.status} />}
        </div>
        <div className="flex gap-2">
          <Link to="/campaigns"><Button variant="ghost">← 返回</Button></Link>
          {!isNew && (c!.status === "sending" || c!.status === "paused") && (
            <Button
              size="md"
              onClick={() =>
                mutateAction(c!.status === "sending"
                  ? `/api/campaigns/${id}/pause`
                  : `/api/campaigns/${id}/resume`)
              }
            >
              {c!.status === "sending" ? "⏸ 暂停" : "▶ 继续"}
            </Button>
          )}
        </div>
      </div>

      {isNew ? (
        <EditorStep
          channels={channels.data || []}
          templates={templates.data || []}
          onCreated={(newId) => navigate(`/campaigns/${newId}`, { replace: true })}
        />
      ) : (
        <DetailBody
          campaign={c!}
          channels={channels.data || []}
          templates={templates.data || []}
          recipients={recipients.data}
          statusFilter={statusFilter}
          setStatusFilter={setStatusFilter}
          mutateAction={mutateAction}
        />
      )}
    </div>
  );

  async function mutateAction(path: string) {
    try {
      await api(path, { method: "POST" });
      await qc.invalidateQueries({ queryKey: ["campaign", id] });
      await qc.invalidateQueries({ queryKey: ["campaigns"] });
    } catch (e) {
      toastError(e);
    }
  }
}

/* ------------------------------------------------ 第①步：编辑内容与收件人 ---- */

function EditorStep({ channels, templates, onCreated }: {
  channels: Channel[]; templates: Template[]; onCreated: (id: number) => void;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [mode, setMode] = useState<EditorMode>("rich");
  const [body, setBody] = useState("");
  const [channelId, setChannelId] = useState<number | "">("");
  const [tagIds, setTagIds] = useState<number[]>([]);
  const [batchSize, setBatchSize] = useState(50);
  const [rate, setRate] = useState(60);

  const tags = useQuery({ queryKey: ["tags"], queryFn: () => api<{ id: number; name: string }[]>("/api/tags") });
  const preview = useQuery({
    queryKey: ["recipients-preview", tagIds],
    queryFn: () => api<{ total: number }>("/api/contacts?page=1&page_size=1&status=active&tag_id=" + tagIds.join(",")),
    enabled: tagIds.length === 0, // 无标签时预览全部 active
  });
  const tagPreview = useQuery({
    queryKey: ["recipients-preview-tag", tagIds],
    queryFn: async () => {
      // 有标签时逐标签统计过于昂贵；给出已选标签提示即可
      return tagIds;
    },
    enabled: tagIds.length > 0,
  });

  const applyTemplate = (tid: string) => {
    const t = templates.find((x) => String(x.id) === tid);
    if (!t) return;
    setSubject(t.subject);
    setBody(t.body);
    setMode(t.mode as EditorMode);
  };

  const create = useMutation({
    mutationFn: () =>
      api<Campaign>("/api/campaigns", {
        method: "POST",
        json: { name, subject, mode, body, channel_id: channelId || null, batch_size: batchSize, rate_per_minute: rate },
      }),
    onSuccess: async (created) => {
      // 直接设定收件人（按标签）
      if (tagIds.length) {
        try {
          await api(`/api/campaigns/${created.id}/recipients`, { method: "PUT", json: { tag_ids: tagIds, contact_ids: [] } });
        } catch (e) {
          toastError(e);
        }
      }
      qc.invalidateQueries({ queryKey: ["campaigns"] });
      toast("活动已创建，请确认发送计划");
      onCreated(created.id);
    },
    onError: toastError,
  });

  return (
    <Card className="space-y-3 p-5">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-fog">活动名称</label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如：八月产品更新" />
        </div>
        <div>
          <label className="mb-1 block text-xs text-fog">发送渠道</label>
          <Select value={channelId} onChange={(e) => setChannelId(e.target.value ? Number(e.target.value) : "")}>
            <option value="">选择渠道…</option>
            {channels.map((ch) => (
              <option key={ch.id} value={ch.id}>{ch.name}（{ch.kind === "resend" ? "Resend" : "SMTP"}）</option>
            ))}
          </Select>
        </div>
      </div>
      <div>
        <label className="mb-1 block text-xs text-fog">主题（支持 {'{{name}}'} 变量）</label>
        <Input value={subject} onChange={(e) => setSubject(e.target.value)} />
      </div>
      {templates.length > 0 && (
        <Select defaultValue="" onChange={(e) => applyTemplate(e.target.value)}>
          <option value="">从模板载入…</option>
          {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </Select>
      )}
      <ModeSwitch mode={mode} onChange={setMode} />
      <Editor3Mode mode={mode} value={body} onChange={setBody} placeholder="正文…支持 {{name}}、{{email}} 变量" />

      <div className="rounded-lg border border-line p-4">
        <p className="mb-2 text-sm font-medium text-neutral-200">收件人（按标签）</p>
        {tags.data?.length ? (
          <div className="flex flex-wrap gap-2">
            {tags.data.map((t) => (
              <button
                key={t.id}
                onClick={() => setTagIds((prev) => (prev.includes(t.id) ? prev.filter((x) => x !== t.id) : [...prev, t.id]))}
                className={`rounded-lg border px-2.5 py-1.5 text-xs transition-colors ${
                  tagIds.includes(t.id) ? "border-accent/50 bg-accent/15 text-accent" : "border-line2 text-fog hover:text-neutral-200"
                }`}
              >
                {t.name}
              </button>
            ))}
          </div>
        ) : (
          <p className="text-xs text-fog">暂无标签，先去导入名单并打标签</p>
        )}
        <p className="mt-2 text-xs text-fog">
          已退订/退信/被标垃圾的联系人会被自动排除 ·
          {tagIds.length === 0 && preview.data ? ` 当前正常联系人约 ${preview.data.total} 位` : " 按所选标签选取"}
          {tagPreview.data && tagPreview.data.length > 0 ? `（已选 ${tagPreview.data.length} 个标签）` : ""}
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-fog">每批数量（批次间隔歇息）</label>
          <Input type="number" min={1} value={batchSize} onChange={(e) => setBatchSize(Number(e.target.value))} />
        </div>
        <div>
          <label className="mb-1 block text-xs text-fog">每分钟发送上限（限速不可关闭）</label>
          <Input type="number" min={1} value={rate} onChange={(e) => setRate(Number(e.target.value))} />
        </div>
      </div>

      <div className="flex justify-end">
        <Button variant="primary" disabled={!name.trim() || !subject.trim() || !body.trim() || create.isPending} onClick={() => create.mutate()}>
          {create.isPending ? "创建中…" : "下一步：确认计划 →"}
        </Button>
      </div>
    </Card>
  );
}

/* ------------------------------------------------ 详情主体 ---- */

function DetailBody({ campaign, channels, templates, recipients, statusFilter, setStatusFilter, mutateAction }: {
  campaign: Campaign; channels: Channel[]; templates: Template[];
  recipients?: RecipientRow; statusFilter: string; setStatusFilter: (s: string) => void;
  mutateAction: (path: string) => Promise<void>;
}) {
  const [tab, setTab] = useState<"content" | "recipients" | "progress">(campaign.status === "draft" ? "content" : "progress");
  const editable = campaign.status === "draft" || campaign.status === "paused" || campaign.status === "planned";

  const tabs = [
    { key: "content", label: "① 内容与设置" },
    { key: "recipients", label: "② 收件人与计划" },
    { key: "progress", label: "③ 进度与时间线" },
  ] as const;

  return (
    <>
      <div className="flex gap-1 rounded-lg border border-line bg-card p-1">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 rounded-md px-3 py-2 text-sm transition-all duration-200 ${
              tab === t.key ? "bg-accent/15 font-medium text-accent" : "text-fog hover:text-neutral-200"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "content" && <ContentTab campaign={campaign} editable={editable} channels={channels} templates={templates} />}
      {tab === "recipients" && <RecipientsTab campaign={campaign} editable={editable} />}
      {tab === "progress" && (
        <ProgressTab campaign={campaign} recipients={recipients} statusFilter={statusFilter}
          setStatusFilter={setStatusFilter} mutateAction={mutateAction} />
      )}
    </>
  );
}

function ContentTab({ campaign, editable, channels, templates }: { campaign: Campaign; editable: boolean; channels: Channel[]; templates: Template[] }) {
  const qc = useQueryClient();
  const [name, setName] = useState(campaign.name);
  const [subject, setSubject] = useState(campaign.subject);
  const [mode, setMode] = useState<EditorMode>(campaign.mode as EditorMode);
  const [body, setBody] = useState(campaign.body);
  const [channelId, setChannelId] = useState<number | "">(campaign.channel_id || "");
  const [checkup, setCheckup] = useState<CheckupResult | null>(null);
  const [atts, setAtts] = useState<AttachInfo[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  const save = useMutation({
    mutationFn: () => api(`/api/campaigns/${campaign.id}`, {
      method: "PUT",
      json: { name, subject, mode, body, channel_id: channelId || null, batch_size: campaign.batch_size, rate_per_minute: campaign.rate_per_minute, max_retries: campaign.max_retries },
    }),
    onSuccess: () => {
      toast("已保存");
      qc.invalidateQueries({ queryKey: ["campaign", String(campaign.id)] });
    },
    onError: toastError,
  });

  const runCheckup = useMutation({
    mutationFn: () => api<CheckupResult>("/api/ai/checkup", { method: "POST", json: { subject, html: body } }),
    onSuccess: setCheckup,
    onError: toastError,
  });

  const uploadFile = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      const isImage = file.type.startsWith("image/");
      if (isImage) form.append("embed", "true");
      return upload(`/api/uploads`, form) as Promise<AttachInfo>;
    },
    onSuccess: (a) => {
      setAtts((prev) => [...prev, a]);
      if (a.cid) {
        toast(`图片已内嵌，CID: ${a.cid}（在 HTML 中引用 src="cid:${a.cid}"）`);
        if (mode === "html") setBody((b) => b + `\n<img src="cid:${a.cid}" alt="${a.filename}" />`);
      } else {
        toast(`附件 ${a.filename} 已上传`);
      }
    },
    onError: toastError,
  });

  return (
    <Card className="space-y-3 p-5">
      {!editable && (
        <p className="rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
          当前状态（{STATUS_LABELS[campaign.status]}）不可编辑内容。
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs text-fog">活动名称</label>
          <Input value={name} onChange={(e) => setName(e.target.value)} disabled={!editable} />
        </div>
        <div>
          <label className="mb-1 block text-xs text-fog">发送渠道</label>
          <Select value={channelId} onChange={(e) => setChannelId(e.target.value ? Number(e.target.value) : "")} disabled={!editable}>
            <option value="">选择渠道…</option>
            {channels.map((ch) => <option key={ch.id} value={ch.id}>{ch.name}（{ch.kind === "resend" ? "Resend" : "SMTP"}）</option>)}
          </Select>
        </div>
      </div>
      <div>
        <label className="mb-1 block text-xs text-fog">主题</label>
        <Input value={subject} onChange={(e) => setSubject(e.target.value)} disabled={!editable} />
      </div>
      {templates.length > 0 && editable && (
        <Select
          defaultValue=""
          onChange={(e) => {
            const t = templates.find((x) => String(x.id) === e.target.value);
            if (t) { setSubject(t.subject); setBody(t.body); setMode(t.mode as EditorMode); }
          }}
        >
          <option value="">从模板载入…</option>
          {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </Select>
      )}
      <ModeSwitch mode={mode} onChange={setMode} />
      {editable ? (
        <Editor3Mode mode={mode} value={body} onChange={setBody} />
      ) : (
        <div className="mail-preview max-h-96 overflow-auto rounded-lg border border-line bg-black/20 p-4 text-sm"
          dangerouslySetInnerHTML={{ __html: body }} />
      )}

      {/* 附件与内嵌图 */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line p-3">
        <span className="text-xs text-fog">📎 附件 / 图片（图片自动生成 CID 内嵌）</span>
        <input ref={fileRef} type="file" hidden multiple onChange={(e) => {
          for (const f of Array.from(e.target.files || [])) uploadFile.mutate(f);
          e.target.value = "";
        }} />
        <Button size="sm" onClick={() => fileRef.current?.click()} disabled={!editable}>上传</Button>
        {atts.map((a) => (
          <span key={a.id} className="rounded border border-line2 px-2 py-1 text-xs text-fog">
            {a.filename}（{fmtBytes(a.size)}{a.cid ? ` · cid:${a.cid}` : ""}）
          </span>
        ))}
      </div>

      <div className="flex justify-between">
        <Button variant="ghost" disabled={runCheckup.isPending || !body.trim()} onClick={() => runCheckup.mutate()}>
          🩺 发送前体检
        </Button>
        <Button variant="primary" disabled={!editable || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "保存中…" : "保存内容"}
        </Button>
      </div>
      {checkup && <CheckupPanel result={checkup} onRewrite={(s) => { /* 改写在模板页提供；此处仅提示 */ toast("可复制建议后手动调整，或从模板页改写"); }} />}
    </Card>
  );
}

import { useRef } from "react";

function RecipientsTab({ campaign, editable }: { campaign: Campaign; editable: boolean }) {
  const qc = useQueryClient();
  const tags = useQuery({ queryKey: ["tags"], queryFn: () => api<{ id: number; name: string }[]>("/api/tags") });
  const [tagIds, setTagIds] = useState<number[]>([]);
  const [plan, setPlan] = useState<CampaignPlan | null>(campaign.plan);

  const stats = useQuery({
    queryKey: ["campaign", String(campaign.id), "recipients", "all"],
    queryFn: () => api<RecipientRow>(`/api/campaigns/${campaign.id}/recipients?page=1&page_size=1`),
  });

  const setRecipients = useMutation({
    mutationFn: () => api(`/api/campaigns/${campaign.id}/recipients`, { method: "PUT", json: { tag_ids: tagIds, contact_ids: [] } }),
    onSuccess: () => {
      toast("收件人已更新");
      qc.invalidateQueries({ queryKey: ["campaign", String(campaign.id)] });
    },
    onError: toastError,
  });

  const genPlan = useMutation({
    mutationFn: () => api<CampaignPlan>(`/api/campaigns/${campaign.id}/plan`, { method: "POST" }),
    onSuccess: (p) => setPlan(p),
    onError: toastError,
  });

  const confirm = useMutation({
    mutationFn: () => api(`/api/campaigns/${campaign.id}/confirm`, { method: "POST" }),
    onSuccess: () => {
      toast("已确认，开始发送（调度器接管）");
      qc.invalidateQueries({ queryKey: ["campaign", String(campaign.id)] });
      qc.invalidateQueries({ queryKey: ["campaigns"] });
    },
    onError: toastError,
  });

  return (
    <div className="space-y-4">
      <Card className="p-5">
        <p className="mb-2 text-sm font-medium text-neutral-200">按标签设定收件人</p>
        <div className="flex flex-wrap gap-2">
          {tags.data?.map((t) => (
            <button
              key={t.id}
              onClick={() => setTagIds((prev) => (prev.includes(t.id) ? prev.filter((x) => x !== t.id) : [...prev, t.id]))}
              className={`rounded-lg border px-2.5 py-1.5 text-xs transition-colors ${
                tagIds.includes(t.id) ? "border-accent/50 bg-accent/15 text-accent" : "border-line2 text-fog hover:text-neutral-200"
              }`}
            >
              {t.name}
            </button>
          ))}
        </div>
        <div className="mt-3 flex items-center justify-between">
          <span className="text-xs text-fog">当前收件人 {fmtNum(stats.data?.total || 0)} 位（自动排除退订/退信/投诉）</span>
          <Button size="sm" disabled={!editable || !tagIds.length || setRecipients.isPending} onClick={() => setRecipients.mutate()}>
            追加所选标签收件人
          </Button>
        </div>
      </Card>

      <Card className="p-5">
        <p className="mb-3 text-sm font-medium text-neutral-200">发送计划（确认前请核对）</p>
        {plan ? (
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
            <PlanStat label="待发送" value={`${plan.total} 位`} />
            <PlanStat label="批次" value={`${plan.batches} 批 × ${plan.batch_size}`} />
            <PlanStat label="限速" value={`${plan.rate_per_minute} 封/分钟`} />
            <PlanStat label="预计耗时" value={`${plan.estimated_minutes} 分钟`} />
            <PlanStat label="渠道" value={plan.channel ? `${plan.channel.name}（${plan.channel.kind}）` : "未选择！"} />
            <PlanStat label="主题" value={plan.subject || "—"} />
          </div>
        ) : (
          <p className="text-xs text-fog">尚未生成计划。设定收件人后点击「生成计划」。</p>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button size="sm" disabled={!editable || genPlan.isPending} onClick={() => genPlan.mutate()}>生成计划</Button>
          <Button size="sm" variant="primary" disabled={!editable || !plan || plan.total === 0 || confirm.isPending} onClick={() => confirm.mutate()}>
            ✓ 确认并发送
          </Button>
        </div>
        <p className="mt-2 text-[11px] text-fog/70">
          确认后调度器按「分批 + 限速 + 指数退避重试」推进；失败自动重试（2^n 分钟退避）。
        </p>
      </Card>
    </div>
  );
}

function PlanStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-black/20 p-3">
      <div className="text-xs text-fog">{label}</div>
      <div className="mt-0.5 truncate font-medium text-neutral-200">{value}</div>
    </div>
  );
}

function ProgressTab({ campaign, recipients, statusFilter, setStatusFilter, mutateAction }: {
  campaign: Campaign; recipients?: RecipientRow; statusFilter: string;
  setStatusFilter: (s: string) => void; mutateAction: (path: string) => Promise<void>;
}) {
  const [detail, setDetail] = useState<Recipient | null>(null);
  const counts = recipients?.counts || campaign.counts || {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-4">
      {campaign.status === "sending" && (
        <p className="rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-xs text-accent">
          正在发送中…页面每 3 秒自动刷新。可随时暂停。
        </p>
      )}

      <Card className="p-5">
        <div className="grid grid-cols-3 gap-3 text-center sm:grid-cols-6">
          {(["sent", "delivered", "opened", "bounced", "complained", "failed", "pending", "skipped"] as const)
            .slice(0, 6)
            .map((k) => (
              <div key={k} className="rounded-lg border border-line bg-black/20 p-3">
                <div className="text-xs text-fog">{STATUS_LABELS[k]}</div>
                <div className={`text-lg font-semibold ${k === "bounced" || k === "complained" || k === "failed" ? "text-bad" : "text-neutral-200"}`}>
                  {fmtNum(counts[k] || 0)}
                </div>
              </div>
            ))}
        </div>
        {campaign.status === "sending" && (
          <div className="mt-3 flex justify-end gap-2">
            <Button size="sm" onClick={() => mutateAction(`/api/campaigns/${campaign.id}/pause`)}>⏸ 暂停</Button>
            <Button size="sm" variant="danger" onClick={() => { if (window.confirm("取消后剩余收件人全部跳过，确定？")) mutateAction(`/api/campaigns/${campaign.id}/cancel`); }}>取消活动</Button>
          </div>
        )}
        {campaign.status === "paused" && (
          <div className="mt-3 flex justify-end gap-2">
            <Button size="sm" variant="primary" onClick={() => mutateAction(`/api/campaigns/${campaign.id}/resume`)}>▶ 继续</Button>
            <Button size="sm" variant="danger" onClick={() => { if (window.confirm("取消后剩余收件人全部跳过，确定？")) mutateAction(`/api/campaigns/${campaign.id}/cancel`); }}>取消活动</Button>
          </div>
        )}
      </Card>

      {(counts.bounced || counts.complained) && (
        <BounceAnalysis campaignId={String(campaign.id)} bounced={counts.bounced || 0} complained={counts.complained || 0} />
      )}

      <Card>
        <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <span className="text-sm font-medium text-white">收件人时间线（{fmtNum(total)}）</span>
          <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">全部状态</option>
            {["pending", "sent", "delivered", "opened", "bounced", "complained", "failed", "skipped"].map((s) => (
              <option key={s} value={s}>{STATUS_LABELS[s]}</option>
            ))}
          </Select>
        </div>
        {recipients?.items.length ? (
          <div className="divide-y divide-line">
            {recipients.items.map((r) => (
              <button key={r.id} onClick={() => setDetail(r)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-white/[0.03]">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-neutral-200">{r.email}</div>
                  {r.error && <div className="truncate text-xs text-bad/80">{r.error}</div>}
                </div>
                <span className="hidden text-xs text-fog md:block">重试 {r.attempts}</span>
                <span className="hidden w-36 text-xs text-fog lg:block">{fmtDateTime(r.sent_at)}</span>
                <Badge value={r.status} />
              </button>
            ))}
          </div>
        ) : (
          <Empty text="暂无收件人数据" />
        )}
      </Card>

      <RecipientDetailModal campaignId={String(campaign.id)} recipient={detail} onClose={() => setDetail(null)} />
    </div>
  );
}

function RecipientDetailModal({ campaignId, recipient, onClose }: { campaignId: string | undefined; recipient: Recipient | null; onClose: () => void }) {
  const q = useQuery({
    queryKey: ["recipient-events", recipient?.id],
    queryFn: () => api<{ recipient: Recipient; events: RecipientEvent[] }>(
      `/api/campaigns/${campaignId}/recipients/${recipient!.id}/events`,
    ),
    enabled: !!recipient,
  });
  return (
    <Modal open={!!recipient} onClose={onClose} title={`时间线 · ${recipient?.email || ""}`}>
      {!q.data ? (
        <Skeleton className="h-32" />
      ) : (
        <div className="space-y-0">
          {q.data.events.map((e, i) => (
            <div key={e.id} className="relative flex gap-3 pb-4 pl-1">
              {i < q.data.events.length - 1 && <div className="absolute left-[7px] top-4 h-full w-px bg-line2" />}
              <div className={`mt-1 h-3.5 w-3.5 shrink-0 rounded-full border-2 ${
                e.type === "bounced" || e.type === "complained" || e.type === "failed"
                  ? "border-bad bg-bad/30"
                  : e.type === "opened"
                    ? "border-ok bg-ok/30"
                    : "border-accent bg-accent/30"
              }`} />
              <div>
                <div className="text-sm text-neutral-200">{STATUS_LABELS[e.type] || e.type}</div>
                <div className="text-xs text-fog">{fmtDateTime(e.created_at)}</div>
                {typeof e.detail?.error === "string" && e.detail.error && (
                  <div className="text-xs text-bad/80">{e.detail.error}</div>
                )}
              </div>
            </div>
          ))}
          {q.data.events.length === 0 && <p className="text-sm text-fog">暂无事件</p>}
        </div>
      )}
    </Modal>
  );
}

function BounceAnalysis({ campaignId, bounced, complained }: { campaignId: string; bounced: number; complained: number }) {
  const [result, setResult] = useState<BounceAnalysisResult | null>(null);
  const analyze = useMutation({
    mutationFn: () => api<BounceAnalysisResult>(`/api/ai/analyze-bounces`, { method: "POST", json: { campaign_id: Number(campaignId) } }),
    onSuccess: (r) => setResult(r),
    onError: toastError,
  });

  return (
    <Card className="p-5">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-medium text-white">发送后归因分析</p>
          <p className="text-xs text-fog">退信 {bounced} · 被标垃圾 {complained} —— AI 分析原因并生成整改版</p>
        </div>
        <Button size="sm" disabled={analyze.isPending} onClick={() => analyze.mutate()}>
          {analyze.isPending ? "分析中…" : "🤖 AI 归因分析"}
        </Button>
      </div>
      {result && (
        <div className="fade-in mt-4 space-y-3 rounded-lg border border-line bg-black/20 p-4">
          <p className="text-sm text-neutral-300">{result.analysis}</p>
          {result.causes.length > 0 && (
            <ul className="space-y-1">
              {result.causes.map((ca, i) => <li key={i} className="text-xs text-warn">⚠ {ca}</li>)}
            </ul>
          )}
          {result.revised_subject && (
            <div className="rounded-lg border border-accent/25 bg-accent/5 p-3">
              <p className="text-xs text-fog">整改版主题</p>
              <p className="text-sm font-medium text-accent">{result.revised_subject}</p>
              <div className="mail-preview mt-2 max-h-60 overflow-auto text-sm text-neutral-300"
                dangerouslySetInnerHTML={{ __html: result.revised_body }} />
              <p className="mt-2 text-[11px] text-fog/70">
                建议新建活动使用整改版，收件人自动排除以上 {result.excluded_emails.length} 个退信/投诉地址与全部退订名单。
              </p>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
