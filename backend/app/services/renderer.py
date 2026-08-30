"""模板渲染：{{var}} 占位符提取与替换、Markdown→HTML、纯文本降级、CID 标记保留。"""

from __future__ import annotations

import re
from html import unescape

VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
VAR_WITH_DEFAULT_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)(?:\|([^}]*))?\s*\}\}")

_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "hr", "table", "pre"}
_BLOCK_RE = re.compile(r"</?(?:" + "|".join(_BLOCK_TAGS) + r")[^>]*>", re.I)


def extract_variables(body: str) -> list[str]:
    """扫描 {{var}} 占位符（保序去重）。"""
    seen: list[str] = []
    for m in VAR_RE.finditer(body or ""):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def render_body(body: str, mode: str, variables: dict[str, str]) -> str:
    """按模式渲染出最终 HTML。mode: rich（HTML）/ markdown / html。"""
    if mode == "markdown":
        html = markdown_to_html(body or "")
    else:
        html = body or ""
    return substitute_variables(html, variables)


def substitute_variables(html: str, variables: dict[str, str]) -> str:
    """替换 {{var}} 与 {{var|默认值}}。值做 HTML 转义。"""
    from html import escape

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        default = m.group(2) if m.lastindex and m.lastindex >= 2 else None
        val = variables.get(key)
        if val is None or val == "":
            if default is not None:
                return escape(default)
            return ""
        return escape(str(val))

    return VAR_WITH_DEFAULT_RE.sub(_sub, html or "")


def markdown_to_html(md: str) -> str:
    from markdown_it import MarkdownIt

    mdit = MarkdownIt("commonmark", {"html": False, "typographer": False}).enable("table")
    return mdit.render(md or "")


def html_to_text(html: str) -> str:
    """粗粒度 HTML→纯文本：块级标签换行、去标签、解实体、压缩空行。"""
    s = html or ""
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", s)
    s = _BLOCK_RE.sub("\n", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = _TAG_RE.sub("", s)
    s = unescape(s)
    lines = [ln.strip() for ln in s.splitlines()]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if ln:
            out.append(ln)
            blank = 0
        else:
            blank += 1
            if blank == 1:
                out.append("")
    return "\n".join(out).strip()


def make_text_version(html: str) -> str:
    """生成纯文本版本（用于 multipart/alternative）。"""
    return html_to_text(html)


def contains_cid(html: str) -> bool:
    return 'src="cid:' in (html or "")


def replace_cid_refs(html: str, mapping: dict[str, str]) -> str:
    """把 src="cid:xxx" 中的 xxx 按映射替换（如上传后重命名）。"""
    for old, new in (mapping or {}).items():
        html = html.replace(f'cid:{old}', f'cid:{new}')
    return html
