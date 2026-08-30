/** 三模式编辑器：TipTap 富文本 / Markdown 源码 / HTML 源码，可即时切换。
 *  切换时把当前内容尽量等价转换（rich ↔ markdown 仅做提示，html 原样保留）。 */

import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import { useEffect } from "react";
import { Button } from "../ui";

export type EditorMode = "rich" | "markdown" | "html";

interface Props {
  mode: EditorMode;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}

export function Editor3Mode({ mode, value, onChange, placeholder }: Props) {
  if (mode === "rich") {
    return <RichEditor value={value} onChange={onChange} placeholder={placeholder} />;
  }
  return <SourceEditor mode={mode} value={value} onChange={onChange} placeholder={placeholder} />;
}

function RichEditor({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Link.configure({ openOnClick: false, HTMLAttributes: { target: "_blank" } }),
      Placeholder.configure({ placeholder: placeholder || "正文…支持 {{name}} 变量占位符" }),
    ],
    content: value || "",
    onUpdate: ({ editor }) => onChange(editor.getHTML()),
    editorProps: { attributes: { class: "tiptap px-4 py-3 text-sm" } },
  });

  // 外部值变化（如 AI 生成、切模板）时同步进编辑器
  useEffect(() => {
    if (editor && value !== editor.getHTML() && !editor.isFocused) {
      editor.commands.setContent(value || "", false);
    }
  }, [value, editor]);

  if (!editor) return null;

  const btn = (label: string, active: boolean, action: () => void, title?: string) => (
    <button
      key={label + title}
      title={title}
      onMouseDown={(e) => e.preventDefault()}
      onClick={action}
      className={`rounded px-2 py-1 text-xs transition-colors ${active ? "bg-accent/20 text-accent" : "text-fog hover:bg-white/5 hover:text-neutral-200"}`}
    >
      {label}
    </button>
  );

  return (
    <div className="overflow-hidden rounded-lg border border-line2 bg-black/30">
      <div className="flex flex-wrap items-center gap-0.5 border-b border-line px-2 py-1.5">
        {btn("B", editor.isActive("bold"), () => editor.chain().focus().toggleBold().run(), "加粗")}
        {btn("I", editor.isActive("italic"), () => editor.chain().focus().toggleItalic().run(), "斜体")}
        {btn("S", editor.isActive("strike"), () => editor.chain().focus().toggleStrike().run(), "删除线")}
        {btn("H3", editor.isActive("heading", { level: 3 }), () => editor.chain().focus().toggleHeading({ level: 3 }).run())}
        {btn("• 列表", editor.isActive("bulletList"), () => editor.chain().focus().toggleBulletList().run())}
        {btn("1. 列表", editor.isActive("orderedList"), () => editor.chain().focus().toggleOrderedList().run())}
        {btn("引用", editor.isActive("blockquote"), () => editor.chain().focus().toggleBlockquote().run())}
        {btn("链接", editor.isActive("link"), () => {
          if (editor.isActive("link")) {
            editor.chain().focus().unsetLink().run();
          } else {
            const url = window.prompt("链接地址：");
            if (url) editor.chain().focus().setLink({ href: url }).run();
          }
        })}
        {btn("代码", editor.isActive("codeBlock"), () => editor.chain().focus().toggleCodeBlock().run())}
        {btn("撤销", false, () => editor.chain().focus().undo().run())}
        {btn("重做", false, () => editor.chain().focus().redo().run())}
      </div>
      <EditorContent editor={editor} />
    </div>
  );
}

function SourceEditor({ mode, value, onChange, placeholder }: { mode: "markdown" | "html"; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder || (mode === "markdown" ? "# Markdown 正文…\n\n支持 {{name}} 变量占位符" : "<p>HTML 正文…支持 {{name}} 变量占位符</p>")}
        spellCheck={false}
        className="h-[320px] w-full resize-y rounded-lg border border-line2 bg-black/30 p-4 font-mono text-sm text-neutral-200 outline-none transition-colors focus:border-accent/60"
      />
      <p className="mt-1.5 text-xs text-fog">
        {mode === "markdown" ? "Markdown 源码模式：发送时自动渲染为 HTML 并生成纯文本版本。" : "HTML 源码模式：请使用邮件安全的内联样式与基础标签。"}
      </p>
    </div>
  );
}

/** 模式切换条。 */
export function ModeSwitch({ mode, onChange }: { mode: EditorMode; onChange: (m: EditorMode) => void }) {
  const modes: { key: EditorMode; label: string }[] = [
    { key: "rich", label: "富文本" },
    { key: "markdown", label: "Markdown" },
    { key: "html", label: "HTML" },
  ];
  return (
    <div className="inline-flex rounded-lg border border-line2 bg-black/30 p-0.5">
      {modes.map((m) => (
        <button
          key={m.key}
          onClick={() => onChange(m.key)}
          className={`rounded-md px-3 py-1.5 text-xs font-medium transition-all duration-200 ${
            mode === m.key ? "bg-accent/20 text-accent" : "text-fog hover:text-neutral-200"
          }`}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}

export { Button };
