/** 会话视图：聚合该联系人全部往来 + AI 摘要 + AI 草拟回复 + 发送回复。 */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Channel, Message } from "../lib/api";
import { Badge, Button, Card, Empty, Input, Select, Skeleton } from "../components/ui";
import { Editor3Mode, ModeSwitch, EditorMode } from "../components/editor/Editor3Mode";
import { fmtDateTime } from "../lib/format";
import { toast, toastError } from "../lib/toast";
import { useTitle } from "../lib/hooks";

interface Detail { message: Message; thread: Message[] }

export default function InboxDetailPage() {
  const { id } = useParams();
  useTitle("会话");
  const qc = useQueryClient();

  const q = useQuery({
    queryKey: ["inbox", id],
    queryFn: () => api<Detail>(`/api/inbox/${id}`),
  });
  const channels = useQuery({ queryKey: ["channels"], queryFn: () => api<Channel[]>("/api/channels") });

  const [mode, setMode] = useState<EditorMode>("rich");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [channelId, setChannelId] = useState<number | "">("");
  const [summary, setSummary] = useState("");
  const [replyToIds, setReplyToIds] = useState<number[]>([]);

  const threadIds = q.data?.thread.map((m) => m.id) || [];

  const summarize = useMutation({
    mutationFn: () => api<{ summary: string }>("/api/ai/summarize", { method: "POST", json: { message_ids: threadIds } }),
    onSuccess: (d) => setSummary(d.summary),
    onError: toastError,
  });

  const draftReply = useMutation({
    mutationFn: (instruction: string) =>
      api<{ subject: string; body: string }>("/api/ai/draft-reply", {
        method: "POST", json: { message_ids: threadIds, instruction },
      }),
    onSuccess: (d) => {
      setSubject(d.subject);
      setBody(d.body);
      toast("AI 已草拟回复，可编辑后发送");
    },
    onError: toastError,
  });

  const sendReply = useMutation({
    mutationFn: () =>
      api<{ results: { email: string; ok: boolean; error?: string }[] }>("/api/inbox/reply", {
        method: "POST",
        json: {
          message_ids: replyToIds.length ? replyToIds : [Number(id)],
          subject, body, mode, channel_id: channelId || null,
        },
      }),
    onSuccess: (d) => {
      const ok = d.results.filter((r) => r.ok).length;
      const bad = d.results.filter((r) => !r.ok);
      if (ok) toast(`已回复 ${ok} 位联系人`);
      bad.forEach((r) => toastError(new Error(`${r.email}: ${r.error}`)));
      setBody("");
      qc.invalidateQueries({ queryKey: ["inbox"] });
    },
    onError: toastError,
  });

  if (q.isLoading) return <div className="space-y-4 p-6"><Skeleton className="h-8 w-64" /><Skeleton className="h-96" /></div>;
  if (!q.data) return <Empty text="邮件不存在" />;

  const main = q.data.message;
  const contactEmail = main.from_email;

  return (
    <div className="mx-auto grid max-w-6xl gap-5 p-6 lg:grid-cols-3">
      {/* 会话 */}
      <div className="space-y-4 lg:col-span-2">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-white">{main.subject || "(无主题)"}</h1>
            <p className="text-xs text-fog">
              来自 {main.from_name || contactEmail} · {fmtDateTime(main.received_at)}
              {main.contact_id && (
                <> · <Link className="text-accent hover:underline" to={`/contacts/${main.contact_id}`}>联系人视图 →</Link></>
              )}
            </p>
          </div>
          <Link to="/inbox"><Button variant="ghost">← 收件箱</Button></Link>
        </div>

        <Card className="space-y-3 p-5">
          {q.data.thread.map((m) => (
            <div
              key={m.id}
              onClick={() => setReplyToIds((prev) => (prev.includes(m.id) ? prev.filter((x) => x !== m.id) : [...prev, m.id]))}
              className={`cursor-pointer rounded-lg border p-3 transition-colors ${
                replyToIds.includes(m.id) ? "border-accent/40 bg-accent/5" : m.direction === "outbound" ? "border-accent/20 bg-accent/[0.03]" : "border-line bg-black/20"
              }`}
            >
              <div className="mb-1.5 flex items-center gap-2 text-xs text-fog">
                <Badge value={m.direction} />
                <span className="font-medium text-neutral-300">{m.direction === "outbound" ? "我" : m.from_name || m.from_email}</span>
                <span className="ml-auto">{fmtDateTime(m.received_at || m.sent_at)}</span>
              </div>
              {m.subject && m.subject !== main.subject && <div className="mb-1 text-sm font-medium text-neutral-200">{m.subject}</div>}
              {m.html ? (
                <div className="mail-preview max-h-72 overflow-auto text-sm text-neutral-300"
                  dangerouslySetInnerHTML={{ __html: m.html }} />
              ) : (
                <p className="whitespace-pre-wrap text-sm text-neutral-300">{m.text}</p>
              )}
            </div>
          ))}
          <p className="text-[11px] text-fog/60">点击会话消息可多选，回复将发给所选消息的发件人（自动去重）。</p>
        </Card>

        {/* 回复编辑 */}
        <Card className="space-y-3 p-5">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-white">回复</p>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="ghost" disabled={summarize.isPending || !threadIds.length} onClick={() => summarize.mutate()}>
                {summarize.isPending ? "摘要中…" : "🤖 AI 会话摘要"}
              </Button>
              <Button size="sm" variant="ghost" disabled={draftReply.isPending || !threadIds.length} onClick={() => draftReply.mutate("")}>
                {draftReply.isPending ? "草拟中…" : "✨ AI 草拟回复"}
              </Button>
            </div>
          </div>
          {summary && (
            <div className="fade-in rounded-lg border border-line bg-black/20 p-3 text-sm text-neutral-300">{summary}</div>
          )}
          <div className="flex gap-2">
            <Input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder={`Re: ${main.subject || ""}`} className="flex-1" />
            <Select value={channelId} onChange={(e) => setChannelId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">回复渠道…</option>
              {channels.data?.map((ch) => <option key={ch.id} value={ch.id}>{ch.name}</option>)}
            </Select>
          </div>
          <ModeSwitch mode={mode} onChange={setMode} />
          <Editor3Mode mode={mode} value={body} onChange={setBody} placeholder="回复内容…" />
          <div className="flex justify-end">
            <Button variant="primary" disabled={!body.trim() || sendReply.isPending} onClick={() => sendReply.mutate()}>
              {sendReply.isPending ? "发送中…" : "发送回复"}
            </Button>
          </div>
        </Card>
      </div>

      {/* 侧栏 */}
      <div className="space-y-4">
        <Card className="p-5">
          <p className="mb-2 text-sm font-medium text-white">联系人</p>
          {main.contact_id ? (
            <Link to={`/contacts/${main.contact_id}`} className="text-sm text-accent hover:underline">
              {contactEmail} → 打开联系人视图
            </Link>
          ) : (
            <p className="text-xs text-fog">{contactEmail}（未关联联系人）</p>
          )}
        </Card>
        <Card className="p-5">
          <p className="mb-2 text-sm font-medium text-white">提示</p>
          <ul className="space-y-1.5 text-xs text-fog">
            <li>· 回复通过所选渠道发送（Resend 或 SMTP）</li>
            <li>· 已退订/退信的联系人会被自动跳过</li>
            <li>· 回复会聚合到该联系人的往来会话</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
