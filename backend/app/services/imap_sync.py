"""IMAP 收件同步与退信扫描（imaplib 同步 API，路由层用线程池或调度器调用）。

支持 QQ/163/Gmail/Outlook/企业邮箱（应用专用密码）。message_id 去重；收件人自动聚合为联系人。
退信扫描：读取 bounce_folder（默认 INBOX），解析 DSN（message/delivery-status）中的
Final-Recipient 与 Action: failed，回写 campaign_recipients.bounced 事件。
"""

from __future__ import annotations

import email
import email.header
import email.policy
import imaplib
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime

from sqlalchemy.orm import Session

from .. import models
from ..models import CampaignRecipient, Contact, Message, RecipientEvent, utcnow


class IMAPError(Exception):
    pass


def _decode_header(raw: str) -> str:
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    out = []
    for data, charset in parts:
        if isinstance(data, bytes):
            out.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            out.append(data)
    return "".join(out)


def imap_connect(config: dict) -> imaplib.IMAP4_SSL | imaplib.IMAP4:
    """从渠道 config 取 imap{host,port,user,password} 建立连接并登录。"""
    icfg = (config or {}).get("imap") or {}
    host = icfg.get("host", "")
    port = int(icfg.get("port", 993) or 993)
    user, password = icfg.get("user", ""), icfg.get("password", "")
    if not host:
        raise IMAPError("IMAP 未配置 host")
    if not user or not password:
        raise IMAPError("IMAP 未配置账号或密码（QQ/163 需使用应用专用密码）")
    try:
        if port == 993:
            client = imaplib.IMAP4_SSL(host, port)
        else:
            client = imaplib.IMAP4(host, port)
            client.starttls()
        client.login(user, password)
        return client
    except imaplib.IMAP4.error as e:
        raise IMAPError(f"IMAP 登录失败: {e}") from e
    except OSError as e:
        raise IMAPError(f"IMAP 连接失败: {e}") from e


def _get_body_parts(msg: email.message.Message) -> tuple[str, str]:
    """提取 (text, html)。"""
    text, html = "", ""

    def walk(part: email.message.Message) -> None:
        nonlocal text, html
        if part.is_multipart():
            for p in part.get_payload():
                walk(p)
            return
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            return
        payload = part.get_payload(decode=True)
        if payload is None:
            return
        charset = part.get_content_charset() or "utf-8"
        content = payload.decode(charset, errors="replace")
        if ctype == "text/plain" and not text:
            text = content
        elif ctype == "text/html" and not html:
            html = content

    walk(msg)
    return text, html


def _upsert_message(db: Session, *, channel_id: int, folder: str, msg: email.message.Message,
                    uid: str) -> bool:
    """按 Message-ID 去重入库，聚合联系人。返回是否新建。"""
    message_id = (msg.get("Message-ID") or f"uid-{uid}").strip()
    if db.query(Message).filter(Message.message_id == message_id).first():
        return False

    from_name, from_email = parseaddr(_decode_header(msg.get("From", "")))
    to_email = parseaddr(_decode_header(msg.get("To", "")))[1]
    subject = _decode_header(msg.get("Subject", ""))
    text, html = _get_body_parts(msg)
    snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", text or html))[:200]

    try:
        received = parsedate_to_datetime(msg.get("Date"))
        if received.tzinfo:
            received = received.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        received = utcnow()

    # 联系人聚合：按发件人邮箱聚合（自己发的除外）
    contact = None
    if from_email:
        contact = db.query(Contact).filter(Contact.email == from_email.lower()).first()
        if contact is None:
            contact = Contact(email=from_email.lower(), name=from_name, source="inbox")
            db.add(contact)
            db.flush()

    db.add(Message(
        direction="inbound",
        contact_id=contact.id if contact else None,
        channel_id=channel_id,
        message_id=message_id,
        in_reply_to=(msg.get("In-Reply-To") or "").strip(),
        from_email=from_email.lower(),
        from_name=from_name,
        to_email=to_email.lower(),
        subject=subject,
        text=text[:20000],
        html=html[:100000],
        snippet=snippet,
        folder=folder,
        received_at=received,
        raw_headers={"message_id": message_id, "in_reply_to": (msg.get("In-Reply-To") or "").strip()},
    ))
    return True


def sync_inbox(db: Session, channel: models.Channel, *, since_days: int = 14, limit: int = 100) -> dict:
    """拉取近期收件并入库。返回 {fetched, new}。"""
    config = channel.config or {}
    folder = (config.get("imap") or {}).get("folder", "INBOX")
    client = imap_connect(config)
    new = 0
    fetched = 0
    try:
        status, _ = client.select(folder, readonly=True)
        if status != "OK":
            raise IMAPError(f"无法打开文件夹 {folder}")
        since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
        status, data = client.search(None, f'(SINCE "{since}")')
        if status != "OK":
            raise IMAPError("IMAP search 失败")
        ids = data[0].split()[-limit:]
        fetched = len(ids)
        for num in reversed(ids):  # 旧→新处理，最新的最后入库
            status, msg_data = client.fetch(num, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            if _upsert_message(db, channel_id=channel.id, folder=folder, msg=msg, uid=num.decode()):
                new += 1
        db.commit()
    finally:
        try:
            client.logout()
        except Exception:
            pass
    return {"fetched": fetched, "new": new}


# ------------------------------------------------------------ 退信扫描 ----

_FINAL_RECIPIENT_RE = re.compile(r"Final-Recipient:\s*rfc822;?\s*([^\s]+)", re.I)
_ACTION_RE = re.compile(r"Action:\s*(\w+)", re.I)


def parse_dsn(raw: bytes) -> dict | None:
    """解析退信（DSN）邮件：返回 {email, action} 或 None。"""
    msg = email.message_from_bytes(raw)
    recipient, action = None, ""
    for part in msg.walk():
        if part.get_content_type() in ("message/delivery-status", "text/plain"):
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            content = payload.decode("utf-8", errors="replace")
            m = _FINAL_RECIPIENT_RE.search(content)
            if m:
                recipient = m.group(1).strip().strip("<>").lower()
            a = _ACTION_RE.search(content)
            if a:
                action = a.group(1).lower()
            if recipient:
                break
    # 非 DSN 结构的退信：常见主题/正文兜底
    if not recipient:
        subject = _decode_header(msg.get("Subject", ""))
        m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", subject + " " + (msg.as_string()[:5000] if "Undelivered" in subject else ""))
        if m and ("undeliver" in subject.lower() or "退信" in subject or "failure" in subject.lower()):
            recipient = m.group(0).lower()
            action = "failed"
    if not recipient:
        return None
    return {"email": recipient, "action": action or "failed"}


def scan_bounces(db: Session, channel: models.Channel, *, since_days: int = 14) -> dict:
    """扫描退信箱，把 failed DSN 回写到对应 campaign_recipient（事件+状态+联系人）。"""
    config = channel.config or {}
    folder = (config.get("imap") or {}).get("bounce_folder", "INBOX")
    client = imap_connect(config)
    detected: list[dict] = []
    try:
        status, _ = client.select(folder, readonly=True)
        if status != "OK":
            raise IMAPError(f"无法打开退信文件夹 {folder}")
        since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
        # 退信通常来自 mailer-daemon / postmaster
        status, data = client.search(None, f'(SINCE "{since}" FROM "mailer-daemon")')
        if status != "OK" or not data or not data[0]:
            status, data = client.search(None, f'(SINCE "{since}")')
        for num in (data[0].split() if data and data[0] else [])[-100:]:
            status, msg_data = client.fetch(num, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                continue
            dsn = parse_dsn(msg_data[0][1])
            if dsn:
                detected.append(dsn)
    finally:
        try:
            client.logout()
        except Exception:
            pass

    applied = 0
    for dsn in detected:
        recipient = (
            db.query(CampaignRecipient)
            .filter(CampaignRecipient.email == dsn["email"])
            .order_by(CampaignRecipient.id.desc())
            .first()
        )
        if recipient and recipient.status not in ("bounced", "complained"):
            now = utcnow()
            recipient.status = "bounced"
            recipient.bounced_at = now
            recipient.error = f"SMTP 硬退信（{dsn['action']}）"
            db.add(RecipientEvent(recipient_id=recipient.id, type="bounced",
                                  detail={"source": "imap_bounce_scan", "action": dsn["action"]}))
            contact = db.get(Contact, recipient.contact_id) if recipient.contact_id else None
            if contact:
                contact.status = "bounced"
            applied += 1
    db.commit()
    return {"scanned": len(detected), "applied": applied, "folder": folder}
