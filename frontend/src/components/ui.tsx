/** UI 基件：Button / Card / Badge / Input / Select / Modal / StatusPill / Empty / Spinner。 */

import { ReactNode, useEffect } from "react";

export function Button({
  children, onClick, variant = "default", size = "md", disabled, type = "button", className = "",
}: {
  children: ReactNode; onClick?: () => void;
  variant?: "default" | "primary" | "ghost" | "danger"; size?: "sm" | "md";
  disabled?: boolean; type?: "button" | "submit"; className?: string;
}) {
  const base =
    "inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed active:scale-[0.98]";
  const variants = {
    default: "border border-line2 bg-white/5 hover:bg-white/10 text-neutral-200",
    primary:
      "bg-gradient-to-b from-accent to-accent/80 text-black hover:brightness-110 shadow-[0_0_20px_rgba(255,176,102,0.25)]",
    ghost: "text-fog hover:text-neutral-200 hover:bg-white/5",
    danger: "border border-bad/30 bg-bad/10 text-bad hover:bg-bad/20",
  };
  const sizes = { sm: "px-2.5 py-1.5 text-xs", md: "px-4 py-2 text-sm" };
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}>
      {children}
    </button>
  );
}

export function Card({ children, className = "", hover = false }: { children: ReactNode; className?: string; hover?: boolean }) {
  return (
    <div className={`rounded-xl border border-line bg-card ${hover ? "card-hover" : ""} ${className}`}>{children}</div>
  );
}

const STATUS_COLORS: Record<string, string> = {
  active: "text-ok border-ok/30 bg-ok/10",
  sent: "text-info border-info/30 bg-info/10",
  delivered: "text-info border-info/30 bg-info/10",
  opened: "text-ok border-ok/30 bg-ok/10",
  bounced: "text-bad border-bad/30 bg-bad/10",
  complained: "text-bad border-bad/30 bg-bad/10",
  unsubscribed: "text-fog border-line2 bg-white/5",
  failed: "text-bad border-bad/30 bg-bad/10",
  skipped: "text-fog border-line2 bg-white/5",
  pending: "text-warn border-warn/30 bg-warn/10",
  sending: "text-accent border-accent/30 bg-accent/10",
  paused: "text-warn border-warn/30 bg-warn/10",
  completed: "text-ok border-ok/30 bg-ok/10",
  cancelled: "text-fog border-line2 bg-white/5",
  draft: "text-fog border-line2 bg-white/5",
  planned: "text-info border-info/30 bg-info/10",
  ok: "text-ok border-ok/30 bg-ok/10",
  error: "text-bad border-bad/30 bg-bad/10",
  unverified: "text-fog border-line2 bg-white/5",
  low: "text-ok border-ok/30 bg-ok/10",
  medium: "text-warn border-warn/30 bg-warn/10",
  high: "text-bad border-bad/30 bg-bad/10",
};

export const STATUS_LABELS: Record<string, string> = {
  active: "正常", unsubscribed: "已退订", bounced: "已退信", complained: "被标垃圾",
  pending: "待发送", sending: "发送中", sent: "已发送", delivered: "已送达",
  opened: "已打开", failed: "失败", skipped: "已跳过", draft: "草稿",
  planned: "已排期", paused: "已暂停", completed: "已完成", cancelled: "已取消",
  ok: "正常", error: "异常", unverified: "未验证", low: "低风险", medium: "中风险", high: "高风险",
  inbound: "收到", outbound: "发出",
};

export function Badge({ value, label }: { value: string; label?: string }) {
  const cls = STATUS_COLORS[value] || "text-fog border-line2 bg-white/5";
  return (
    <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-medium ${cls}`}>
      {label || STATUS_LABELS[value] || value}
    </span>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const { className = "", ...rest } = props;
  return (
    <input
      {...rest}
      className={`w-full rounded-lg border border-line2 bg-black/30 px-3 py-2 text-sm text-neutral-200 placeholder:text-fog/60 outline-none transition-colors focus:border-accent/60 ${className}`}
    />
  );
}

export function Textarea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const { className = "", ...rest } = props;
  return (
    <textarea
      {...rest}
      className={`w-full rounded-lg border border-line2 bg-black/30 px-3 py-2 text-sm text-neutral-200 placeholder:text-fog/60 outline-none transition-colors focus:border-accent/60 ${className}`}
    />
  );
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  const { className = "", children, ...rest } = props;
  return (
    <select
      {...rest}
      className={`rounded-lg border border-line2 bg-black/30 px-3 py-2 text-sm text-neutral-200 outline-none transition-colors focus:border-accent/60 [&>option]:bg-card ${className}`}
    >
      {children}
    </select>
  );
}

export function Modal({ open, onClose, title, children, wide = false }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean;
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={onClose}>
      <div
        className={`fade-in max-h-[85vh] w-full overflow-auto rounded-xl border border-line2 bg-card p-5 shadow-2xl ${wide ? "max-w-3xl" : "max-w-lg"}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-base font-semibold text-white">{title}</h3>
          <button onClick={onClose} className="text-fog hover:text-white">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Empty({ text, hint }: { text: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 py-16 text-center">
      <div className="text-3xl opacity-40">✉️</div>
      <div className="text-sm text-fog">{text}</div>
      {hint && <div className="text-xs text-fog/60">{hint}</div>}
    </div>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h2 className="text-sm font-semibold text-white">{children}</h2>
      {right}
    </div>
  );
}
