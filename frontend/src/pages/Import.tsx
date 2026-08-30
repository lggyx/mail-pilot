/** 名单导入向导：文件（CSV/XLSX/JSON/TXT）或粘贴 → 标签选择 → 报告。 */

import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ImportReport, upload } from "../lib/api";
import { Button, Card, Select, Skeleton, Textarea } from "../components/ui";
import { toast, toastError } from "../lib/toast";
import { useTitle } from "../lib/hooks";

export default function ImportPage() {
  useTitle("导入名单");
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [text, setText] = useState("");
  const [tagIds, setTagIds] = useState<number[]>([]);
  const [newTag, setNewTag] = useState("");
  const [report, setReport] = useState<ImportReport | null>(null);

  const tags = useQuery({ queryKey: ["tags"], queryFn: () => api<{ id: number; name: string }[]>("/api/tags") });

  const ensureTag = async (name: string): Promise<number | null> => {
    if (!name.trim()) return null;
    const t = await api<{ id: number }>("/api/tags", { method: "POST", json: { name: name.trim() } });
    return t.id;
  };

  const doImport = useMutation({
    mutationFn: async (payload: FormData) => {
      const data = await upload("/api/contacts/import", payload);
      return data as ImportReport;
    },
    onSuccess: (data) => {
      setReport(data);
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["tags"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      toast(`导入完成：新增 ${data.added}，更新 ${data.updated}`);
    },
    onError: toastError,
  });

  const buildTags = async () => {
    const ids = [...tagIds];
    const created = await ensureTag(newTag);
    if (created) ids.push(created);
    return JSON.stringify(ids);
  };

  const submitText = async () => {
    try {
      const form = new FormData();
      form.append("text", text);
      form.append("fmt", "paste");
      form.append("tag_ids", await buildTags());
      doImport.mutate(form);
      setNewTag("");
    } catch (e) {
      toastError(e);
    }
  };

  const submitFile = async (file: File) => {
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("tag_ids", await buildTags());
      doImport.mutate(form);
      setNewTag("");
    } catch (e) {
      toastError(e);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-6">
      <div>
        <h1 className="text-xl font-semibold text-white">导入名单</h1>
        <p className="text-xs text-fog">
          支持 CSV / XLSX / JSON / TXT（每行一个邮箱）/ 直接粘贴；自动去重、校验格式、
          与退订名单求差。请只导入<strong className="text-neutral-300">拥有同意关系</strong>的联系人。
        </p>
      </div>

      <Card className="p-5">
        <div
          className="flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-line2 py-10 transition-colors hover:border-accent/50"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            const f = e.dataTransfer.files?.[0];
            if (f) submitFile(f);
          }}
        >
          <div className="text-2xl">📥</div>
          <p className="text-sm text-fog">拖拽文件到此处，或</p>
          <Button onClick={() => fileRef.current?.click()}>选择文件</Button>
          <input
            ref={fileRef}
            type="file"
            accept=".csv,.xlsx,.json,.txt"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) submitFile(f);
              e.target.value = "";
            }}
          />
          <p className="text-[11px] text-fog/70">.csv / .xlsx / .json / .txt（≤20MB）</p>
        </div>
      </Card>

      <Card className="p-5">
        <p className="mb-2 text-sm font-medium text-neutral-200">或直接粘贴（每行一个：email / 姓名 &lt;email&gt; / email, 姓名）</p>
        <Textarea
          rows={7}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={"zhang@example.com\n李四 <li@example.com>\nwang@example.com, 王五"}
          className="font-mono"
        />
      </Card>

      <Card className="p-5">
        <p className="mb-2 text-sm font-medium text-neutral-200">打标签（可多选 + 新建）</p>
        <div className="flex flex-wrap items-center gap-2">
          {tags.isLoading ? (
            <Skeleton className="h-8 w-40" />
          ) : (
            tags.data?.map((t) => (
              <button
                key={t.id}
                onClick={() =>
                  setTagIds((prev) => (prev.includes(t.id) ? prev.filter((x) => x !== t.id) : [...prev, t.id]))
                }
                className={`rounded-lg border px-2.5 py-1.5 text-xs transition-colors ${
                  tagIds.includes(t.id) ? "border-accent/50 bg-accent/15 text-accent" : "border-line2 text-fog hover:text-neutral-200"
                }`}
              >
                {t.name}
              </button>
            ))
          )}
          <input
            value={newTag}
            onChange={(e) => setNewTag(e.target.value)}
            placeholder="新建标签…"
            className="w-28 rounded-lg border border-line2 bg-black/30 px-2.5 py-1.5 text-xs outline-none focus:border-accent/60"
          />
        </div>
        <div className="mt-4 flex justify-end">
          <Button variant="primary" disabled={(!text.trim() && !doImport.isPending) || doImport.isPending} onClick={submitText}>
            {doImport.isPending ? "导入中…" : "导入粘贴内容"}
          </Button>
        </div>
      </Card>

      {report && (
        <Card className="fade-in p-5">
          <h2 className="mb-3 text-sm font-semibold text-white">导入报告</h2>
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
            <Stat label="解析行数" value={report.total_rows} />
            <Stat label="新增" value={report.added} tone="ok" />
            <Stat label="更新" value={report.updated} tone="info" />
            <Stat label="文件内重复跳过" value={report.skipped_duplicates} />
            <Stat label="退订/退信/投诉排除" value={report.excluded_unsubscribed} tone="warn" />
            <Stat label="无效条目" value={report.invalid_count} tone="bad" />
          </div>
          {report.invalid.length > 0 && (
            <div className="mt-3 max-h-40 overflow-auto rounded-lg border border-line bg-black/20 p-3">
              {report.invalid.map((r, i) => (
                <div key={i} className="text-xs text-fog">
                  <span className="text-bad">✕</span> {r.raw || "(空)"} — {r.reason}
                </div>
              ))}
            </div>
          )}
          <div className="mt-4 flex gap-2">
            <Link to="/contacts"><Button>查看联系人 →</Button></Link>
            <Button variant="ghost" onClick={() => { setReport(null); setText(""); }}>继续导入</Button>
          </div>
        </Card>
      )}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "ok" | "bad" | "warn" | "info" }) {
  const colors = { ok: "text-ok", bad: "text-bad", warn: "text-warn", info: "text-info" };
  return (
    <div className="rounded-lg border border-line bg-black/20 p-3">
      <div className="text-xs text-fog">{label}</div>
      <div className={`text-lg font-semibold ${tone ? colors[tone] : "text-neutral-200"}`}>{value}</div>
    </div>
  );
}
