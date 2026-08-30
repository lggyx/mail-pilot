/** 联系人详情：资料 + 发送历史 + 往来会话（收件箱聚合）。 */

import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, Contact, Message } from "../lib/api";
import { Badge, Button, Card, Empty, SectionTitle, Skeleton, STATUS_LABELS } from "../components/ui";
import { fmtDateTime } from "../lib/format";
import { useTitle } from "../lib/hooks";

interface Detail {
  contact: Contact;
  thread: Message[];
  campaign_history: {
    campaign_id: number; campaign_name: string; status: string;
    sent_at: string | null; bounced_at: string | null; complained_at: string | null;
  }[];
}

export default function ContactDetailPage() {
  const { id } = useParams();
  useTitle("联系人详情");
  const q = useQuery({
    queryKey: ["contact", id],
    queryFn: () => api<Detail>(`/api/contacts/${id}`),
  });

  if (q.isLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-40" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (!q.data) return <Empty text="联系人不存在" />;
  const { contact, thread, campaign_history } = q.data;

  return (
    <div className="space-y-5 p-6">
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-xl font-semibold text-white">{contact.name || contact.email}</h1>
            <Badge value={contact.status} />
          </div>
          <p className="mt-0.5 text-xs text-fog">{contact.email} · {fmtDateTime(contact.created_at)} 加入</p>
        </div>
        <Link to="/contacts"><Button variant="ghost">← 返回</Button></Link>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card className="p-5">
            <SectionTitle>往来会话（收件箱聚合）</SectionTitle>
            {thread.length ? (
              <div className="space-y-3">
                {thread.map((m) => (
                  <div key={m.id} className={`fade-in rounded-lg border p-3 ${m.direction === "outbound" ? "border-accent/25 bg-accent/5" : "border-line bg-black/20"}`}>
                    <div className="mb-1 flex items-center gap-2 text-xs text-fog">
                      <Badge value={m.direction} />
                      <span>{m.direction === "outbound" ? `发给 ${m.to_email}` : `来自 ${m.from_name || m.from_email}`}</span>
                      <span className="ml-auto">{fmtDateTime(m.received_at || m.sent_at)}</span>
                    </div>
                    {m.subject && <div className="mb-1 text-sm font-medium text-neutral-200">{m.subject}</div>}
                    <p className="line-clamp-4 whitespace-pre-wrap text-sm text-fog">{m.text || m.snippet}</p>
                    <Link to={`/inbox/${m.id}`} className="mt-2 inline-block text-xs text-accent hover:underline">
                      在收件箱中打开 →
                    </Link>
                  </div>
                ))}
              </div>
            ) : (
              <Empty text="还没有往来邮件" hint="配置 IMAP 渠道后自动同步收件" />
            )}
          </Card>
        </div>

        <div className="space-y-5">
          <Card className="p-5">
            <SectionTitle>发送历史</SectionTitle>
            {campaign_history.length ? (
              <div className="space-y-2">
                {campaign_history.map((h) => (
                  <Link key={h.campaign_id} to={`/campaigns/${h.campaign_id}`} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm transition-colors hover:bg-white/5">
                    <Badge value={h.status} />
                    <span className="flex-1 truncate text-fog">{h.campaign_name}</span>
                    <span className="text-xs text-fog/70">{fmtDateTime(h.sent_at)}</span>
                  </Link>
                ))}
              </div>
            ) : (
              <p className="text-xs text-fog">尚未参与任何活动</p>
            )}
          </Card>

          <Card className="p-5">
            <SectionTitle>标签</SectionTitle>
            <div className="flex flex-wrap gap-1.5">
              {contact.tags.length ? (
                contact.tags.map((t) => (
                  <span key={t.id} className="rounded-md border border-line2 px-2 py-1 text-xs" style={{ color: t.color }}>
                    {t.name}
                  </span>
                ))
              ) : (
                <p className="text-xs text-fog">无标签</p>
              )}
            </div>
          </Card>

          <Card className="p-5">
            <SectionTitle>状态说明</SectionTitle>
            <ul className="space-y-1.5 text-xs text-fog">
              <li>· 正常：可被选入发送活动</li>
              <li>· 已退订 / 已退信 / 被标垃圾：导入与发送时自动排除（状态 {STATUS_LABELS[contact.status]}）</li>
              <li>· 退信与标垃圾事件由渠道 webhook 或退信箱扫描自动回写</li>
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
