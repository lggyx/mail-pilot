"""名单导入：CSV / XLSX / JSON / TXT / 粘贴文本 → 联系人。

自动去重（文件内 + 库内）、格式校验、与退订/退信/投诉名单求差集、打标签。
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import Contact, Tag
from ..utils.email_addr import extract_entries, is_valid_email

EMAIL_KEYS = {"email", "mail", "邮箱", "邮件", "电子邮箱", "e-mail", "email地址"}
NAME_KEYS = {"name", "姓名", "名字", "昵称", "称呼", "联系人"}

# 不可再发状态（导入时求差集排除）
BLOCKED_STATUSES = {"unsubscribed", "bounced", "complained"}


@dataclass
class ImportRow:
    email: str
    name: str = ""
    valid: bool = True
    reason: str = ""  # invalid 时的原因


@dataclass
class ImportReport:
    added: int = 0
    updated: int = 0
    skipped_duplicates: int = 0      # 文件内或库内重复
    excluded_unsubscribed: int = 0   # 已退订/退信/投诉被排除
    invalid: list[dict] = field(default_factory=list)  # [{"raw":..., "reason":...}]
    total_rows: int = 0

    def as_dict(self) -> dict:
        return {
            "total_rows": self.total_rows,
            "added": self.added,
            "updated": self.updated,
            "skipped_duplicates": self.skipped_duplicates,
            "excluded_unsubscribed": self.excluded_unsubscribed,
            "invalid_count": len(self.invalid),
            "invalid": self.invalid[:50],
        }


def _row_to_entry(row: dict | list | str) -> ImportRow:
    """把一行数据转成 (email, name)。"""
    if isinstance(row, str):
        email, name = "", ""
        entries = extract_entries(row)
        if entries:
            email, name = entries[0]
        return ImportRow(email=email, name=name, valid=is_valid_email(email),
                         reason="" if email else "未找到有效邮箱")
    if isinstance(row, list):
        row = {str(i): v for i, v in enumerate(row)}
    if isinstance(row, dict):
        lowered = {str(k).strip().lower(): v for k, v in row.items()}
        email_raw = next((lowered[k] for k in lowered if k in EMAIL_KEYS and lowered[k]), "")
        name_raw = next((lowered[k] for k in lowered if k in NAME_KEYS and lowered[k]), "")
        if not email_raw:
            # 无表头匹配：取第一个像邮箱的值
            for v in lowered.values():
                if isinstance(v, str) and "@" in v:
                    email_raw = v
                    break
        email = str(email_raw or "").strip().lower()
        name = str(name_raw or "").strip()
        if not name and email:
            import re as _re
            m = _re.match(r'^(.*?)\s*<', str(email_raw or ""))
            if m and m.group(1).strip():
                name = m.group(1).strip().strip('"')
        return ImportRow(email=email, name=name, valid=is_valid_email(email),
                         reason="" if email else "缺少邮箱字段")
    return ImportRow(email="", valid=False, reason="无法识别的行")


def parse_rows(content: bytes | str, fmt: str) -> list[ImportRow]:
    """按格式解析为行条目。fmt: csv/xlsx/json/txt/paste"""
    if fmt in ("txt", "paste"):
        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
        out: list[ImportRow] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            entries = extract_entries(line)
            if entries:
                out.extend(ImportRow(email=e, name=n, valid=True) for e, n in entries)
            elif "@" in line:  # 含 @ 但解析不出合法邮箱 → 记为无效行
                out.append(ImportRow(email=line.strip(",;"), valid=False, reason="邮箱格式无效"))
        return out

    if fmt == "json":
        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content
        data = json.loads(text)
        if isinstance(data, dict):  # {"contacts": [...]} 包装
            data = next((v for v in data.values() if isinstance(v, list)), [data])
        if not isinstance(data, list):
            raise ValueError("JSON 应为对象数组或字符串数组")
        return [_row_to_entry(item) for item in data]

    if fmt == "csv":
        text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)
        rows = list(reader)
        return _table_rows_to_entries(rows)

    if fmt == "xlsx":
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(bytes(content)), read_only=True, data_only=True)
        ws = wb.active
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
        return _table_rows_to_entries(rows)

    raise ValueError(f"不支持的格式: {fmt}")


def _table_rows_to_entries(rows: list) -> list[ImportRow]:
    """带表头的表格（CSV/XLSX）：首行识别列名；无表头时整体按文本解析。"""
    if not rows:
        return []
    header = [("" if c is None else str(c).strip().lower()) for c in rows[0]]
    has_header = any(h in EMAIL_KEYS for h in header)
    if not has_header:
        # 无表头：把每行拼成文本按自由文本解析
        lines = [", ".join("" if c is None else str(c) for c in r) for r in rows]
        return [_row_to_entry(line) for line in lines]
    email_idx = next(i for i, h in enumerate(header) if h in EMAIL_KEYS)
    name_idx = next((i for i, h in enumerate(header) if h in NAME_KEYS), -1)
    out: list[ImportRow] = []
    for r in rows[1:]:
        if r is None or all(c is None or str(c).strip() == "" for c in r):
            continue
        email = str(r[email_idx] or "").strip().lower() if email_idx < len(r) else ""
        name = str(r[name_idx] or "").strip() if name_idx >= 0 and name_idx < len(r) else ""
        out.append(ImportRow(email=email, name=name, valid=is_valid_email(email),
                             reason="" if email else "缺少邮箱"))
    return out


def import_contacts(
    db: Session,
    rows: list[ImportRow],
    *,
    tag_ids: list[int] | None = None,
    source: str = "import",
) -> ImportReport:
    """执行导入：去重、校验、退订差集、入库、打标签。"""
    report = ImportReport(total_rows=len(rows))
    tags = db.query(Tag).filter(Tag.id.in_(tag_ids or [])).all()

    seen: set[str] = set()
    pending: dict[str, str] = {}  # email -> name（保持顺序）
    for i, row in enumerate(rows, start=1):
        raw = row.email or f"(第{i}行)"
        if not row.valid:
            report.invalid.append({"raw": raw, "reason": row.reason or "邮箱格式无效"})
            continue
        if row.email in seen or row.email in pending:
            report.skipped_duplicates += 1
            continue
        seen.add(row.email)
        pending[row.email] = row.name

    if pending:
        existing = db.query(Contact).filter(Contact.email.in_(pending.keys())).all()
        existing_map = {c.email: c for c in existing}
    else:
        existing_map = {}

    for email, name in pending.items():
        contact = existing_map.get(email)
        if contact and contact.status in BLOCKED_STATUSES:
            report.excluded_unsubscribed += 1
            continue
        if contact:
            if name and not contact.name:
                contact.name = name
            report.updated += 1
        else:
            contact = Contact(email=email, name=name, source=source)
            db.add(contact)
            db.flush()
            report.added += 1
        for tag in tags:
            if tag not in contact.tags:
                contact.tags.append(tag)

    db.commit()
    return report
