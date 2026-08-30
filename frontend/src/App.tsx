/** 路由与布局：左侧栏 + 顶栏 + 懒加载页面 + 登录守卫 + 全局快捷键。 */

import { Suspense, lazy, useCallback, useMemo, useRef, useState } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "./lib/api";
import { useGlobalShortcuts } from "./lib/hooks";
import { Button, Skeleton } from "./components/ui";

const LoginPage = lazy(() => import("./pages/Login"));
const DashboardPage = lazy(() => import("./pages/Dashboard"));
const ContactsPage = lazy(() => import("./pages/Contacts"));
const ContactDetailPage = lazy(() => import("./pages/ContactDetail"));
const ImportPage = lazy(() => import("./pages/Import"));
const TemplatesPage = lazy(() => import("./pages/Templates"));
const TemplateEditorPage = lazy(() => import("./pages/TemplateEditor"));
const CampaignsPage = lazy(() => import("./pages/Campaigns"));
const CampaignDetailPage = lazy(() => import("./pages/CampaignDetail"));
const InboxPage = lazy(() => import("./pages/Inbox"));
const InboxDetailPage = lazy(() => import("./pages/InboxDetail"));
const SettingsPage = lazy(() => import("./pages/Settings"));

const NAV = [
  { to: "/", label: "概览", icon: "◈", key: "D" },
  { to: "/contacts", label: "联系人", icon: "◉", key: "C" },
  { to: "/templates", label: "模板", icon: "▤", key: "T" },
  { to: "/campaigns", label: "活动", icon: "✈", key: "M" },
  { to: "/inbox", label: "收件箱", icon: "☰", key: "I" },
  { to: "/settings", label: "设置", icon: "⚙", key: "S" },
];

function PageSkeleton() {
  return (
    <div className="space-y-4 p-6">
      <Skeleton className="h-8 w-48" />
      <div className="grid grid-cols-4 gap-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <Skeleton className="h-64" />
    </div>
  );
}

export default function App() {
  const location = useLocation();
  const isLogin = location.pathname === "/login";

  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<{ username: string }>("/api/auth/me"),
    retry: false,
  });

  if (isLogin) {
    return (
      <Suspense fallback={null}>
        <LoginPage />
      </Suspense>
    );
  }
  if (me.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-sm text-fog">加载中…</div>
      </div>
    );
  }
  if (me.isError) return <Navigate to="/login" replace />;

  return (
    <Layout username={me.data?.username || ""}>
      <Suspense fallback={<PageSkeleton />}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/contacts" element={<ContactsPage />} />
          <Route path="/contacts/import" element={<ImportPage />} />
          <Route path="/contacts/:id" element={<ContactDetailPage />} />
          <Route path="/templates" element={<TemplatesPage />} />
          <Route path="/templates/:id" element={<TemplateEditorPage />} />
          <Route path="/campaigns" element={<CampaignsPage />} />
          <Route path="/campaigns/:id" element={<CampaignDetailPage />} />
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/inbox/:id" element={<InboxDetailPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </Layout>
  );
}

function Layout({ username, children }: { username: string; children: React.ReactNode }) {
  const navigate = useNavigate();
  const searchRef = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState("");
  const unread = useQuery({
    queryKey: ["inbox", "unread-count"],
    queryFn: () => api<{ count: number }>("/api/inbox/unread-count"),
    refetchInterval: 30_000,
  });

  const onCompose = useCallback(() => navigate("/campaigns/new", { state: { compose: true } }), [navigate]);
  const onSearch = useCallback(() => searchRef.current?.focus(), []);
  useGlobalShortcuts(navigate, { onCompose, onSearch });

  const doSearch = useMemo(
    () => () => {
      if (!search.trim()) return;
      navigate(`/contacts?q=${encodeURIComponent(search.trim())}`);
      setSearch("");
    },
    [search, navigate],
  );

  const logout = async () => {
    await api("/api/auth/logout", { method: "POST" });
    window.location.href = "/login";
  };

  return (
    <div className="flex min-h-screen">
      {/* 侧栏 */}
      <aside className="fixed inset-y-0 left-0 z-30 flex w-52 flex-col border-r border-line bg-card/60 backdrop-blur">
        <div className="flex items-center gap-2 px-5 py-5">
          <span className="text-lg">✈️</span>
          <span className="text-[15px] font-semibold tracking-wide text-white">mail-pilot</span>
        </div>
        <nav className="flex-1 space-y-0.5 px-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `group flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-all duration-200 ${
                  isActive ? "bg-accent/15 text-accent" : "text-fog hover:bg-white/5 hover:text-neutral-200"
                }`
              }
            >
              <span className="w-4 text-center opacity-80">{item.icon}</span>
              <span className="flex-1">{item.label}</span>
              {item.to === "/inbox" && (unread.data?.count || 0) > 0 && (
                <span className="rounded-full bg-accent/20 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
                  {unread.data!.count}
                </span>
              )}
              <kbd className="hidden text-[10px] text-fog/50 group-hover:inline">{item.key}</kbd>
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-line px-3 py-3">
          <Button variant="primary" size="md" className="w-full" onClick={onCompose}>
            ✎ 写信 <kbd className="text-[10px] opacity-60">C</kbd>
          </Button>
        </div>
      </aside>

      {/* 主区 */}
      <div className="ml-52 flex min-h-screen flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-line bg-ink/80 px-6 py-3 backdrop-blur">
          <div className="relative flex-1 max-w-md">
            <input
              ref={searchRef}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && doSearch()}
              placeholder="搜索联系人 / 邮件…  按 / 聚焦"
              className="w-full rounded-lg border border-line bg-black/30 py-1.5 pl-8 pr-3 text-sm outline-none transition-colors placeholder:text-fog/60 focus:border-accent/60"
            />
            <span className="absolute left-2.5 top-1.5 text-xs text-fog">⌕</span>
          </div>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="text-fog">{username}</span>
            <button onClick={logout} className="text-fog transition-colors hover:text-bad">
              退出
            </button>
          </div>
        </header>
        <main className="flex-1">{children}</main>
        <footer className="border-t border-line px-6 py-3 text-xs text-fog/60">
          快捷键：j/k 列表导航 · c 写信 · g+字母 跳页 · / 搜索 · 合规提醒：仅向有同意关系的联系人发送
        </footer>
      </div>
    </div>
  );
}
