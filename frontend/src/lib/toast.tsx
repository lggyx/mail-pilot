/** 轻量 Toast 系统（context-free：命令式调用 + 订阅渲染）。 */

import { useEffect, useState } from "react";

export interface Toast {
  id: number;
  kind: "ok" | "bad" | "info";
  text: string;
}

type Listener = (toasts: Toast[]) => void;

let toasts: Toast[] = [];
const listeners = new Set<Listener>();
let seq = 1;

function emit() {
  for (const l of listeners) l([...toasts]);
}

export function toast(text: string, kind: Toast["kind"] = "ok") {
  const t: Toast = { id: seq++, kind, text };
  toasts = [...toasts, t];
  emit();
  window.setTimeout(() => {
    toasts = toasts.filter((x) => x.id !== t.id);
    emit();
  }, 3200);
}

export function toastError(e: unknown) {
  toast(e instanceof Error ? e.message : String(e), "bad");
}

export function ToastHost() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    listeners.add(setItems);
    return () => {
      listeners.delete(setItems);
    };
  }, []);
  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2">
      {items.map((t) => (
        <div
          key={t.id}
          className={`fade-in pointer-events-auto rounded-lg border px-4 py-2.5 text-sm shadow-xl backdrop-blur ${
            t.kind === "ok"
              ? "border-ok/30 bg-ok/10 text-ok"
              : t.kind === "bad"
                ? "border-bad/30 bg-bad/10 text-bad"
                : "border-line2 bg-card2 text-neutral-200"
          }`}
        >
          {t.text}
        </div>
      ))}
    </div>
  );
}
