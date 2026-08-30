/** 模板编辑：三模式编辑器 + AI 代写（意图）/ 改写 / 垃圾箱风险体检。 */

import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, CheckupResult, Template } from "../lib/api";
import { Badge, Button, Card, Input, Skeleton } from "../components/ui";
import { Editor3Mode, ModeSwitch, EditorMode } from "../components/editor/Editor3Mode";
import { Input as TextInput } from "../components/ui";
import { toast, toastError } from "../lib/toast";
import { useTitle } from "../lib/hooks";

export default function TemplateEditorPage() {
  const { id } = useParams();
  const isNew = !id || id === "new";
  const navigate = useNavigate();
  const qc = useQueryClient();
  useTitle(isNew ? "新建模板" : "编辑模板");

  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [mode, setMode] = useState<EditorMode>("rich");
  const [body, setBody] = useState("");
  const [aiIntent, setAiIntent] = useState("");
  const [aiInstruction, setAiInstruction] = useState("");
  const [checkup, setCheckup] = useState<CheckupResult | null>(null);

  const existing = useQuery({
    queryKey: ["template", id],
    queryFn: () => api<Template>(`/api/templates/${id}`),
    enabled: !isNew,
  });

  useEffect(() => {
    if (existing.data) {
      setName(existing.data.name);
      setSubject(existing.data.subject);
      setMode(existing.data.mode as EditorMode);
      setBody(existing.data.body);
    }
  }, [existing.data]);

  const save = useMutation({
    mutationFn: () => {
      const payload = { name, subject, mode, body };
      return isNew
        ? api<Template>("/api/templates", { method: "POST", json: payload })
        : api<Template>(`/api/templates/${id}`, { method: "PUT", json: payload });
    },
    onSuccess: (t) => {
      toast("已保存");
      qc.invalidateQueries({ queryKey: ["templates"] });
      if (isNew) navigate(`/templates/${t.id}`, { replace: true });
    },
    onError: toastError,
  });

  const aiGenerate = useMutation({
    mutationFn: () => api<{ subject: string; body: string }>("/api/ai/generate", {
      method: "POST", json: { intent: aiIntent, mode: mode === "html" ? "rich" : mode },
    }),
    onSuccess: (d) => {
      setSubject(d.subject);
      setBody(d.body);
      toast("AI 已生成，可继续编辑");
    },
    onError: toastError,
  });

  const aiRewrite = useMutation({
    mutationFn: () => api<{ subject: string; body: string }>("/api/ai/rewrite", {
      method: "POST",
      json: { subject, body, instruction: aiInstruction, mode: mode === "html" ? "rich" : mode },
    }),
    onSuccess: (d) => {
      setSubject(d.subject);
      setBody(d.body);
      toast("AI 已改写");
    },
    onError: toastError,
  });

  const runCheckup = useMutation({
    mutationFn: () => api<CheckupResult>("/api/ai/checkup", {
      method: "POST",
      json: { subject, html: mode === "markdown" ? body : body },
    }),
    onSuccess: setCheckup,
    onError: toastError,
  });

  return (
    <div className="mx-auto max-w-4xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">{isNew ? "新建模板" : "编辑模板"}</h1>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => navigate("/templates")}>← 返回</Button>
          <Button variant="primary" onClick={() => save.mutate()} disabled={save.isPending || !name.trim()}>
            {save.isPending ? "保存中…" : "保存"}
          </Button>
        </div>
      </div>

      <Card className="space-y-3 p-5">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs text-fog">模板名称</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如：v2.0 更新通知" />
          </div>
          <div>
            <label className="mb-1 block text-xs text-fog">邮件主题（支持 {'{{name}}'} 变量）</label>
            <Input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="{{name}}，这是我们最新的更新" />
          </div>
        </div>

        {/* AI 代写 */}
        <div className="rounded-lg border border-accent/25 bg-accent/5 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-accent">✨ AI 代写</span>
            <TextInput
              value={aiIntent}
              onChange={(e) => setAiIntent(e.target.value)}
              placeholder="一句话意图，如：给订阅用户发 v2.0 更新通知，重点讲性能提升"
              className="min-w-[280px] flex-1 !py-1.5 text-xs"
              onKeyDown={(e) => e.key === "Enter" && aiIntent.trim() && aiGenerate.mutate()}
            />
            <Button size="sm" variant="primary" disabled={!aiIntent.trim() || aiGenerate.isPending} onClick={() => aiGenerate.mutate()}>
              {aiGenerate.isPending ? "生成中…" : "生成"}
            </Button>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <ModeSwitch mode={mode} onChange={setMode} />
          <span className="text-xs text-fog">切换模式保留当前内容</span>
        </div>

        <Editor3Mode mode={mode} value={body} onChange={setBody} />

        {/* AI 改写 + 体检 */}
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line p-3">
          <span className="text-xs font-medium text-fog">✨ AI 改写</span>
          <TextInput
            value={aiInstruction}
            onChange={(e) => setAiInstruction(e.target.value)}
            placeholder="改写要求（可空）：更口语化 / 更简洁 / 增强行动点"
            className="min-w-[240px] flex-1 !py-1.5 text-xs"
          />
          <Button size="sm" disabled={aiRewrite.isPending || !body.trim()} onClick={() => aiRewrite.mutate()}>
            {aiRewrite.isPending ? "改写中…" : "改写"}
          </Button>
          <Button size="sm" variant="ghost" disabled={runCheckup.isPending || !body.trim()} onClick={() => runCheckup.mutate()}>
            {runCheckup.isPending ? "体检中…" : "🩺 垃圾箱风险体检"}
          </Button>
        </div>

        {checkup && <CheckupPanel result={checkup} onRewrite={(s) => { setAiInstruction(s); aiRewrite.mutate(); }} />}
      </Card>
    </div>
  );
}

export function CheckupPanel({ result, onRewrite }: { result: CheckupResult; onRewrite?: (instruction: string) => void }) {
  return (
    <div className="fade-in rounded-lg border border-line bg-black/20 p-4">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm font-semibold text-white">体检结果</span>
        <Badge value={result.level} />
        <span className="text-lg font-bold text-accent">{result.score}</span>
        <span className="text-xs text-fog">/100（越高越安全）</span>
        {!result.ai_available && (
          <span className="ml-auto text-[11px] text-warn">
            {result.ai_error ? "AI 不可用，仅本地规则" : "未配置 AI，仅本地规则"}
          </span>
        )}
      </div>
      {result.issues.length > 0 && (
        <ul className="mb-2 space-y-1">
          {result.issues.map((iss, i) => (
            <li key={i} className="flex items-start gap-1.5 text-xs">
              <span className={iss.severity === "high" ? "text-bad" : iss.severity === "medium" ? "text-warn" : "text-fog"}>
                ●
              </span>
              <span className="text-neutral-300">{iss.message}</span>
            </li>
          ))}
        </ul>
      )}
      <ul className="mb-2 space-y-1">
        {result.suggestions.map((s, i) => (
          <li key={i} className="text-xs text-fog">→ {s}</li>
        ))}
      </ul>
      {onRewrite && result.suggestions.length > 0 && (
        <Button size="sm" onClick={() => onRewrite("按体检建议整改：移除风险表达、优化结构与可读性，保持原意")}>
          一键按建议改写
        </Button>
      )}
    </div>
  );
}
