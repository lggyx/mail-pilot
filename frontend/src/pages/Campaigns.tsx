/** 活动列表：状态徽标 + 进度 + 计数。 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, Campaign } from "../lib/api";
import { Badge, Button, Card, Empty, Skeleton } from "../components/ui";
import { fmtTime } from "../lib/format";
import { useTitle } from "../lib/hooks";

export default function CampaignsPage() {
  useTitle("活动");
  const q = useQuery({
    queryKey: ["campaigns"],
    queryFn: () => api<{ items: Campaign[]; total: number }>("/api/campaigns?page=1&page_size=100"),
    refetchInterval: (query) =>
      query.state.data?.items.some((c) => c.status === "sending") ? 3000 : false,
  });

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">发送活动</h1>
          <p className="text-xs text-fog">批量发送：计划确认 → 限速分批 → 逐收件人状态时间线</p>
        </div>
        <Link to="/campaigns/new">
          <Button variant="primary">＋ 新建活动</Button>
        </Link>
      </div>

      {q.isLoading ? (
        <div className="space-y-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-20" />)}
        </div>
      ) : q.data?.items.length ? (
        <div className="space-y-3">
          {q.data.items.map((cp, i) => {
            const total = Object.values(cp.counts || {}).reduce((a, b) => a + b, 0);
            const done = (cp.counts?.sent || 0) + (cp.counts?.delivered || 0) + (cp.counts?.opened || 0)
              + (cp.counts?.bounced || 0) + (cp.counts?.complained || 0) + (cp.counts?.failed || 0) + (cp.counts?.skipped || 0);
            const pct = total ? Math.round((done / total) * 100) : 0;
            return (
              <Link key={cp.id} to={`/campaigns/${cp.id}`} className={`fade-in-${(i % 4) + 1} block`}>
                <Card hover className="p-4">
                  <div className="flex items-center gap-3">
                    <Badge value={cp.status} />
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-white">{cp.name}</div>
                      <div className="truncate text-xs text-fog">{cp.subject || "（无主题）"}</div>
                    </div>
                    <div className="hidden items-center gap-4 text-xs text-fog md:flex">
                      <span>已发 {cp.counts?.sent || 0}</span>
                      <span className="text-bad">退信 {cp.counts?.bounced || 0}</span>
                      <span className="text-warn">标垃圾 {cp.counts?.complained || 0}</span>
                      <span>{fmtTime(cp.created_at)}</span>
                    </div>
                  </div>
                  {(cp.status === "sending" || cp.status === "paused" || cp.status === "completed") && total > 0 && (
                    <div className="mt-3 h-1.5 overflow-hidden rounded bg-white/5">
                      <div
                        className="h-full rounded bg-gradient-to-r from-accent to-accent/60 transition-all duration-700"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  )}
                </Card>
              </Link>
            );
          })}
        </div>
      ) : (
        <Empty text="还没有活动" hint="「新建活动」→ 选收件人 → 确认计划 → 发送" />
      )}
    </div>
  );
}
