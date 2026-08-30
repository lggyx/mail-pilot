/** 模板列表。 */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, Template } from "../lib/api";
import { Button, Card, Empty, Skeleton } from "../components/ui";
import { fmtTime } from "../lib/format";
import { useTitle } from "../lib/hooks";

export default function TemplatesPage() {
  useTitle("模板");
  const q = useQuery({ queryKey: ["templates"], queryFn: () => api<Template[]>("/api/templates") });

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-white">模板</h1>
          <p className="text-xs text-fog">复用邮件内容与结构；变量占位符 {'{{name}}'} 按收件人替换</p>
        </div>
        <Link to="/templates/new">
          <Button variant="primary">＋ 新建模板</Button>
        </Link>
      </div>

      {q.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => <Skeleton key={i} className="h-36" />)}
        </div>
      ) : q.data?.length ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {q.data.map((t, i) => (
            <Link key={t.id} to={`/templates/${t.id}`} className={`fade-in-${(i % 4) + 1}`}>
              <Card hover className="flex h-full flex-col p-5">
                <div className="flex items-center justify-between">
                  <h3 className="truncate font-medium text-white">{t.name}</h3>
                  <span className="rounded border border-line2 px-1.5 py-0.5 text-[10px] text-fog">
                    {t.mode === "rich" ? "富文本" : t.mode === "markdown" ? "Markdown" : "HTML"}
                  </span>
                </div>
                <p className="mt-1 truncate text-sm text-fog">{t.subject || "（无主题）"}</p>
                <p className="mt-2 line-clamp-3 flex-1 whitespace-pre-wrap text-xs text-fog/80">
                  {t.body.replace(/<[^>]+>/g, " ").slice(0, 120) || "（空）"}
                </p>
                <div className="mt-3 flex items-center justify-between text-xs text-fog/70">
                  <span>{t.variables.length ? `变量：${t.variables.slice(0, 3).join(", ")}` : "无变量"}</span>
                  <span>{fmtTime(t.updated_at)}</span>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      ) : (
        <Empty text="还没有模板" hint="新建模板，或用 AI 从一句话意图生成" />
      )}
    </div>
  );
}
