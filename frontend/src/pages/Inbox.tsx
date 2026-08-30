/** 收件箱：IMAP 同步入口、未读/全部/归档筛选、多选批量操作（已读/归档/删除）、j/k 导航。 */

import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Message } from "../lib/api";
import { Badge, Button, Card, Empty, Skeleton } from "../components/ui";
import { fmtTime } from "../lib/format";
import { toast, toastError } from "../lib/toast";
import { useListNav, useTitle } from "../lib/hooks";

export default function InboxPage() {
  useTitle("收件箱");
  const [params, setParams] = useState<{ filter: string; q: string }>({ filter: "all", q: "" });
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const list = useQuery({
    queryKey: ["inbox", params],
    queryFn: () =>
      api<{ items: Message[]; total: number }>(
        `/api/inbox?page=1&page_size=100&filter=${params.filter}&q=${encodeURIComponent(params.q)}`,
      ),
    refetchInterval: 30_000,
  });
  const channels = useQuery({ queryKey: ["channels"], queryFn: () => api<{ id: number; name: string; kind: string; config: Record<string, unknown> }[]>("/api/channels") });
  const hasImap = (channels.data || []).some(
    (c) => c.kind === "smtp" && (c.config?.imap as Record<string, unknown> | undefined)?.host,
  );

  const sync = useMutation({
    mutationFn: () => api<{ channel: string; ok: boolean; inbox?: { new: number }; error?: string }[]>("/api/inbox/sync", { method: "POST" }),
    onSuccess: (data) => {
      const ok = data.filter((r) => r.ok);
      const failed = data.filter((r) => !r.ok);
      if (ok.length) toast(`同步完成：新增 ${ok.reduce((a, r) => a + (r.inbox?.new || 0), 0)} 封`);
      failed.forEach((f) => toastError(new Error(`${f.channel}: ${f.error}`)));
      qc.invalidateQueries({ queryKey: ["inbox"] });
    },
    onError: toastError,
  });

  const batch = useMutation({
    mutationFn: (action: string) => api<{ affected: number }>("/api/inbox/batch", { method: "POST", json: { ids: [...selected], action } }),
    onSuccess: (d, action) => {
      toast(`${LABELS[action] || action} ${d.affected} 封`);
      setSelected(new Set());
      qc.invalidateQueries({ queryKey: ["inbox"] });
    },
    onError: toastError,
  });

  const { ref, active, setActive } = useListNav<HTMLDivElement>((idx) => {
    const m = list.data?.items[idx];
    if (m) navigate(`/inbox/${m.id}`);
  });

  const toggle = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold text-white">收件箱</h1>
          <p className="text-xs text-fog">IMAP 同步任意平台邮箱（QQ/163/Gmail/Outlook 需应用专用密码）· j/k 导航</p>
        </div>
        <div className="flex items-center gap-2">
          {(["all", "unread", "archived"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setParams((p) => ({ ...p, filter: f }))}
              className={`rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                params.filter === f ? "border-accent/50 bg-accent/15 text-accent" : "border-line2 text-fog hover:text-neutral-200"
              }`}
            >
              {f === "all" ? "全部" : f === "unread" ? "未读" : "已归档"}
            </button>
          ))}
          <Button size="sm" variant="primary" disabled={!hasImap || sync.isPending} onClick={() => sync.mutate()}>
            {sync.isPending ? "同步中…" : "⟳ 同步 IMAP"}
          </Button>
        </div>
      </div>

      {!hasImap && (
        <p className="rounded-lg border border-info/30 bg-info/10 px-3 py-2 text-xs text-info">
          尚未配置 IMAP 渠道：到 <Link to="/settings" className="underline">设置 → 渠道管理</Link> 配置 SMTP 渠道并填写 IMAP 信息后即可收信。
        </p>
      )}

      {selected.size > 0 && (
        <Card className="fade-in flex items-center gap-2 p-3">
          <span className="text-xs text-fog">已选 {selected.size} 封：</span>
          <Button size="sm" onClick={() => batch.mutate("read")}>标记已读</Button>
          <Button size="sm" onClick={() => batch.mutate("unread")}>标记未读</Button>
          <Button size="sm" onClick={() => batch.mutate(params.filter === "archived" ? "unarchive" : "archive")}>
            {params.filter === "archived" ? "取消归档" : "归档"}
          </Button>
          <Button size="sm" variant="danger" onClick={() => { if (window.confirm(`删除 ${selected.size} 封？`)) batch.mutate("delete"); }}>删除</Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>取消选择</Button>
        </Card>
      )}

      <Card>
        {list.isLoading ? (
          <div className="space-y-2 p-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-12" />)}</div>
        ) : list.data?.items.length ? (
          <div ref={ref} className="divide-y divide-line">
            {list.data.items.map((m, idx) => (
              <div
                key={m.id}
                data-nav
                onClick={() => navigate(`/inbox/${m.id}`)}
                onMouseEnter={() => setActive(idx)}
                className={`flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors ${
                  active === idx ? "bg-accent/10" : "hover:bg-white/[0.03]"
                }`}
              >
                <input
                  type="checkbox"
                  checked={selected.has(m.id)}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => toggle(m.id)}
                  className="accent-accent"
                />
                <span className={`h-2 w-2 shrink-0 rounded-full ${m.is_read ? "bg-transparent" : "bg-accent"}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className={`w-40 truncate text-sm ${m.is_read ? "text-fog" : "font-medium text-white"}`}>
                      {m.from_name || m.from_email}
                    </span>
                    <span className={`truncate text-sm ${m.is_read ? "text-fog" : "text-neutral-200"}`}>{m.subject || "(无主题)"}</span>
                  </div>
                  <div className="truncate text-xs text-fog/70">{m.snippet}</div>
                </div>
                <span className="w-20 shrink-0 text-right text-xs text-fog">{fmtTime(m.received_at)}</span>
              </div>
            ))}
          </div>
        ) : (
          <Empty text="收件箱为空" hint="点击「同步 IMAP」拉取最新邮件" />
        )}
      </Card>
    </div>
  );
}

const LABELS: Record<string, string> = { read: "已读", unread: "未读", archive: "归档", unarchive: "取消归档", delete: "删除" };
