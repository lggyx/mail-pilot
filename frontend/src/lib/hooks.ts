/** 通用 hooks：列表 j/k 导航、全局快捷键、页面标题。 */

import { useEffect, useRef, useState } from "react";

/** 全局快捷键：c=写信 / g d=概览 / g c=联系人 / g t=模板 / g m=活动 / g i=收件箱 / g s=设置 / /=搜索 */
export function useGlobalShortcuts(
  navigate: (to: string) => void,
  opts: { onCompose?: () => void; onSearch?: () => void } = {},
) {
  const chord = useRef(false);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return;
      if (chord.current) {
        chord.current = false;
        const map: Record<string, string> = {
          d: "/", c: "/contacts", t: "/templates", m: "/campaigns", i: "/inbox", s: "/settings",
        };
        const to = map[e.key];
        if (to) {
          e.preventDefault();
          navigate(to);
        }
        return;
      }
      if (e.key === "g") {
        chord.current = true;
        window.setTimeout(() => (chord.current = false), 900);
        return;
      }
      if (e.key === "c" && opts.onCompose) {
        e.preventDefault();
        opts.onCompose();
      } else if (e.key === "/" && opts.onSearch) {
        e.preventDefault();
        opts.onSearch();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [navigate, opts.onCompose, opts.onSearch]);
}

/** 列表 j/k 导航 + Enter 打开：容器内所有 [data-nav] 元素按 DOM 顺序导航。 */
export function useListNav<T extends HTMLElement>(onOpen?: (index: number) => void) {
  const ref = useRef<T>(null);
  const [active, setActive] = useState(-1);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return;
      const items = ref.current?.querySelectorAll<HTMLElement>("[data-nav]");
      if (!items || items.length === 0) return;
      if (e.key === "j" || e.key === "k") {
        e.preventDefault();
        const dir = e.key === "j" ? 1 : -1;
        setActive((prev) => {
          const next = Math.min(items.length - 1, Math.max(0, (prev < 0 ? (dir > 0 ? 0 : items.length - 1) : prev + dir)));
          items[next]?.scrollIntoView({ block: "nearest" });
          return next;
        });
      } else if (e.key === "Enter" && active >= 0) {
        onOpen?.(active);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [active, onOpen]);

  return { ref, active, setActive };
}

export function useTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · mail-pilot`;
  }, [title]);
}
