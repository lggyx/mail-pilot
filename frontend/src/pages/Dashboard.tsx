/** 概览：统计卡（CountUp 动效）+ 送达漏斗 + 最近活动。 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, Campaign, DashboardStats } from "../lib/api";
import { Card, Badge, SectionTitle, Skeleton, Empty } from "../components/ui";
import { CountUp } from "../components/CountUp";
import { fmtTime, fmtPct } from "../lib/format";
import { useTitle } from "../lib/hooks";

export default function DashboardPage() {
  useTitle("概览");
  const stats = useQuery({ queryKey: ["dashboard"], queryFn: () => api<DashboardStats>("/api/dashboard/stats") });
  const campaigns = useQuery({
    queryKey: ["campaigns", { page: 1, page_size: 6 }],
    queryFn: () => api<{ items: Campaign[] }>("/api/campaigns?page=1&page_size=6"),
  });

  if (stats.isLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-40" />
        <div className="grid grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}
        </div>
        <Skeleton className="h-72" />
      </div>
    );
  }

  const d = stats.data?.delivery;
  const c = stats.data?.contacts;

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-xl font-semibold text-white">概览</h1>
        <p className="text-xs text-fog">发送健康度与名单质量一览</p>
      </div>

      {/* 统计卡 */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Card hover className="fade-in p-5">
          <div className="text-xs text-fog">联系人</div>
          <div className="mt-1 text-2xl font-semibold text-white"><CountUp value={c?.total || 0} /></div>
          <div className="mt-1 text-xs text-fog">正常 {c?.active ?? 0} · 退订 {c?.unsubscribed ?? 0}</div>
        </Card>
        <Card hover className="fade-in-1 p-5">
          <div className="text-xs text-fog">送达率</div>
          <div className="mt-1 text-2xl font-semibold text-white">
            <CountUp value={d?.deliver_rate ?? 0} decimals={1} suffix="%" />
          </div>
          <div className="mt-1 text-xs text-fog">送达 {d?.delivered ?? 0} / 发送 {d?.sent ?? 0}</div>
        </Card>
        <Card hover className="fade-in-2 p-5">
          <div className="text-xs text-fog">打开率</div>
          <div className="mt-1 text-2xl font-semibold text-white">
            <CountUp value={d?.open_rate ?? 0} decimals={1} suffix="%" />
          </div>
          <div className="mt-1 text-xs text-fog">打开 {d?.opened ?? 0}</div>
        </Card>
        <Card hover className="fade-in-3 p-5">
          <div className="text-xs text-fog">异常信号</div>
          <div className="mt-1 text-2xl font-semibold text-white">
            <CountUp value={(d?.bounced ?? 0) + (d?.complained ?? 0)} />
          </div>
          <div className="mt-1 text-xs text-fog">退信 {d?.bounced ?? 0} · 标垃圾 {d?.complained ?? 0}</div>
        </Card>
      </div>

      {/* 送达漏斗 */}
      <Card className="p-5">
        <SectionTitle>送达漏斗（全部活动累计）</SectionTitle>
        {d && d.sent > 0 ? (
          <div className="space-y-2.5">
            <FunnelRow label="发送" value={d.sent} total={d.sent} color="from-info/60 to-info/30" />
            <FunnelRow label="送达" value={d.delivered} total={d.sent} color="from-accent/70 to-accent/30" />
            <FunnelRow label="打开" value={d.opened} total={d.sent} color="from-ok/70 to-ok/30" />
            <FunnelRow label="退信" value={d.bounced} total={d.sent} color="from-bad/70 to-bad/30" />
            <FunnelRow label="标垃圾" value={d.complained} total={d.sent} color="from-warn/70 to-warn/30" />
            <p className="pt-1 text-[11px] text-fog/70">
              打开率基于送达口径 {fmtPct(d.open_rate)}；退信/标垃圾会自动把联系人标记为不可发送。
            </p>
          </div>
        ) : (
          <Empty text="还没有发送数据" hint="去「活动」创建第一个发送活动" />
        )}
      </Card>

      {/* 最近活动 */}
      <Card className="p-5">
        <SectionTitle right={<Link to="/campaigns" className="text-xs text-accent hover:underline">全部 →</Link>}>
          最近活动
        </SectionTitle>
        {campaigns.data?.items?.length ? (
          <div className="divide-y divide-line">
            {campaigns.data.items.map((cp) => (
              <Link key={cp.id} to={`/campaigns/${cp.id}`} className="flex items-center gap-3 py-2.5 transition-colors hover:bg-white/[0.03]">
                <Badge value={cp.status} />
                <span className="flex-1 truncate text-sm text-neutral-200">{cp.name}</span>
                <span className="text-xs text-fog">{cp.counts?.sent || 0} 发送</span>
                <span className="w-20 text-right text-xs text-fog">{fmtTime(cp.created_at)}</span>
              </Link>
            ))}
          </div>
        ) : (
          <Empty text="暂无活动" />
        )}
      </Card>
    </div>
  );
}

function FunnelRow({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div className="flex items-center gap-3 text-sm">
      <span className="w-14 text-fog">{label}</span>
      <div className="h-5 flex-1 overflow-hidden rounded-md bg-white/5">
        <div
          className={`h-full rounded-md bg-gradient-to-r ${color} transition-all duration-700`}
          style={{ width: `${Math.max(pct, value > 0 ? 2 : 0)}%` }}
        />
      </div>
      <span className="w-24 text-right text-xs text-neutral-300">{value}（{pct}%）</span>
    </div>
  );
}
