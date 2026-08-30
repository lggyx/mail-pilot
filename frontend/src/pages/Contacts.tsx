/** 联系人列表：搜索/状态/标签筛选、j/k 导航、行内快捷操作。 */

import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Contact } from "../lib/api";
import { Badge, Button, Card, Empty, Input, Select, Skeleton } from "../components/ui";
import { fmtTime } from "../lib/format";
import { toast, toastError } from "../lib/toast";
import { useListNav, useTitle } from "../lib/hooks";

export default function ContactsPage() {
  useTitle("联系人");
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const q = params.get("q") || "";
  const status = params.get("status") || "";
  const tagId = params.get("tag_id") || "";
  const page = Number(params.get("page") || 1);

  const contacts = useQuery({
    queryKey: ["contacts", { q, status, tagId, page }],
    queryFn: () =>
      api<{ items: Contact[]; total: number }>(
        `/api/contacts?page=${page}&page_size=50&q=${encodeURIComponent(q)}&status=${status}&tag_id=${tagId}`,
      ),
  });
  const tags = useQuery({ queryKey: ["tags"], queryFn: () => api<{ id: number; name: string }[]>("/api/tags") });

  const { ref, active, setActive } = useListNav<HTMLDivElement>(
    (idx) => {
      const c = contacts.data?.items[idx];
      if (c) navigate(`/contacts/${c.id}`);
    },
  );

  const setUnsub = useMutation({
    mutationFn: (c: Contact) =>
      api(`/api/contacts/${c.id}`, {
        method: "PUT",
        json: { status: c.status === "unsubscribed" ? "active" : "unsubscribed" },
      }),
    onSuccess: () => {
      toast("已更新状态");
      qc.invalidateQueries({ queryKey: ["contacts"] });
    },
    onError: toastError,
  });

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("page");
    setParams(next);
  };

  const totalPages = Math.max(1, Math.ceil((contacts.data?.total || 0) / 50));

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">联系人</h1>
          <p className="text-xs text-fog">
            {contacts.data ? `${contacts.data.total} 位联系人 · 仅向有同意关系的地址发送` : "加载中…"}
          </p>
        </div>
        <Link to="/contacts/import">
          <Button variant="primary">＋ 导入名单</Button>
        </Link>
      </div>

      <div className="flex flex-wrap gap-2">
        <Input
          placeholder="搜索邮箱或姓名…"
          defaultValue={q}
          className="max-w-xs"
          onKeyDown={(e) => e.key === "Enter" && setFilter("q", (e.target as HTMLInputElement).value)}
          onBlur={(e) => e.target.value !== q && setFilter("q", e.target.value)}
        />
        <Select value={status} onChange={(e) => setFilter("status", e.target.value)}>
          <option value="">全部状态</option>
          <option value="active">正常</option>
          <option value="unsubscribed">已退订</option>
          <option value="bounced">已退信</option>
          <option value="complained">被标垃圾</option>
        </Select>
        <Select value={tagId} onChange={(e) => setFilter("tag_id", e.target.value)}>
          <option value="">全部标签</option>
          {tags.data?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </Select>
      </div>

      <Card>
        {contacts.isLoading ? (
          <div className="space-y-2 p-4">
            {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-10" />)}
          </div>
        ) : contacts.data?.items.length ? (
          <div ref={ref} className="divide-y divide-line">
            {contacts.data.items.map((c, idx) => (
              <div
                key={c.id}
                data-nav
                onClick={() => navigate(`/contacts/${c.id}`)}
                onMouseEnter={() => setActive(idx)}
                className={`flex cursor-pointer items-center gap-3 px-4 py-2.5 transition-colors ${
                  active === idx ? "bg-accent/10" : "hover:bg-white/[0.03]"
                }`}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm text-neutral-200">{c.email}</span>
                    {c.tags.map((t) => (
                      <span key={t.id} className="rounded border border-line2 px-1.5 py-0.5 text-[10px]" style={{ color: t.color }}>
                        {t.name}
                      </span>
                    ))}
                  </div>
                  <div className="text-xs text-fog">{c.name || "—"}</div>
                </div>
                <span className="hidden w-24 text-xs text-fog lg:block">{c.source === "inbox" ? "来自收件" : "导入"}</span>
                <span className="hidden w-32 text-xs text-fog md:block">最近 {fmtTime(c.last_email_at)}</span>
                <Badge value={c.status} />
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setUnsub.mutate(c);
                  }}
                  className="rounded px-2 py-1 text-xs text-fog transition-colors hover:bg-white/5 hover:text-bad"
                  title={c.status === "unsubscribed" ? "恢复为正常" : "标记为退订"}
                >
                  {c.status === "unsubscribed" ? "恢复" : "退订"}
                </button>
              </div>
            ))}
          </div>
        ) : (
          <Empty text="没有匹配的联系人" hint="导入名单后开始使用" />
        )}
      </Card>

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2 text-sm text-fog">
          <Button size="sm" disabled={page <= 1} onClick={() => setFilter("page", String(page - 1))}>上一页</Button>
          <span>{page} / {totalPages}</span>
          <Button size="sm" disabled={page >= totalPages} onClick={() => setFilter("page", String(page + 1))}>下一页</Button>
        </div>
      )}
    </div>
  );
}
