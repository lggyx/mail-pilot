"""邮箱地址解析/规范化/校验与文本名单解析。"""

from __future__ import annotations

import re

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

# 匹配文本中的任意邮箱（用于从 "Name <a@b>" 或杂乱行中提取）
EMAIL_FIND_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

DISPLAY_RE = re.compile(r"^(?P<name>[^<]*?)\s*<(?P<email>[^>]+)>\s*$")


def normalize_email(raw: str) -> str:
    """规范化：去空白/尖括号/mailto:，转小写。"""
    s = (raw or "").strip().strip("<>").strip()
    s = re.sub(r"^mailto:", "", s, flags=re.I)
    return s.lower()


def is_valid_email(s: str) -> bool:
    return bool(s) and len(s) <= 320 and EMAIL_RE.match(s) is not None


def parse_addr(raw: str) -> tuple[str, str]:
    """解析 "Name <a@b.c>" / "a@b.c" / "a@b.c, Name" → (email, name)。"""
    s = (raw or "").strip()
    m = DISPLAY_RE.match(s)
    if m:
        email = normalize_email(m.group("email"))
        name = m.group("name").strip().strip('"').strip()
        return (email, name)
    # "email, name" 或 "email; name" 形式
    if ("," in s or ";" in s) and "@" in s:
        parts = re.split(r"[;,]", s, maxsplit=1)
        email = normalize_email(parts[0])
        name = parts[1].strip().strip('"') if len(parts) > 1 else ""
        return (email, name)
    return (normalize_email(s), "")


def extract_entries(text: str) -> list[tuple[str, str]]:
    """从自由文本（TXT 每行一条 / 富文本粘贴）提取 (email, name) 列表。

    不去重（由导入层统计 skipped_duplicates）；支持每行："a@b.c"、"Name <a@b.c>"、
    "a@b.c, Name"；混排时按行提取邮箱并尽量取称呼。
    """
    out: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip().strip(",;")
        if not line:
            continue
        email, name = parse_addr(line)
        if not is_valid_email(email):
            # 行内混有其他文字：找出邮箱，称呼取邮箱前的中文/字母串
            found = EMAIL_FIND_RE.findall(line)
            if not found:
                continue
            email = normalize_email(found[0])
            if not is_valid_email(email):
                continue
            before = line.split(found[0])[0].strip(" ,;:\t（）()[]【】")
            name = before if 0 < len(before) <= 64 else ""
        out.append((email, name))
    return out
