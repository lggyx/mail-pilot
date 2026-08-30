"""发送通道：Resend HTTP API（httpx）与通用 SMTP（stdlib，同步、线程池执行）。

统一入口 send_message() 返回 (provider_message_id, error)；附件与内嵌图（CID）两渠道都支持。
"""

from __future__ import annotations

import base64
import email.utils
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx


@dataclass
class OutgoingAttachment:
    filename: str
    content: bytes
    mime: str = "application/octet-stream"
    cid: str | None = None  # 有 cid → 内嵌图（multipart/related）


@dataclass
class OutgoingMessage:
    from_addr: str          # "Name <a@b.c>" 或 "a@b.c"
    to: str                 # 单个收件人地址（逐人发送，收件人只看到自己）
    subject: str
    html: str = ""
    text: str = ""
    reply_to: str = ""
    headers: dict[str, str] = field(default_factory=dict)  # 如 List-Unsubscribe
    attachments: list[OutgoingAttachment] = field(default_factory=list)


class SendError(Exception):
    pass


# ---------------------------------------------------------------- Resend ----

def send_via_resend(config: dict, msg: OutgoingMessage, timeout: float = 30.0) -> str:
    """Resend /emails 端点。返回 provider message id；失败抛 SendError。"""
    api_key = (config or {}).get("api_key", "")
    if not api_key:
        raise SendError("Resend 渠道缺少 api_key")

    payload: dict = {
        "from": msg.from_addr,
        "to": [msg.to],
        "subject": msg.subject,
    }
    if msg.html:
        payload["html"] = msg.html
    if msg.text:
        payload["text"] = msg.text
    if msg.reply_to:
        payload["reply_to"] = msg.reply_to
    if msg.headers:
        payload["headers"] = msg.headers
    if msg.attachments:
        payload["attachments"] = [
            {
                "filename": a.filename,
                "content": base64.b64encode(a.content).decode(),
                "content_type": a.mime,
                **({"content_id": a.cid} if a.cid else {}),
            }
            for a in msg.attachments
        ]

    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        raise SendError(f"Resend 网络错误: {e}") from e

    if resp.status_code in (200, 201):
        data = resp.json()
        mid = data.get("id", "")
        if not mid:
            raise SendError("Resend 返回缺少 id")
        return mid
    # 429 限速：交给上层按重试逻辑退避
    detail = resp.text[:300]
    raise SendError(f"Resend HTTP {resp.status_code}: {detail}")


# ------------------------------------------------------------------ SMTP ----

def _build_mime(msg: OutgoingMessage) -> MIMEMultipart:
    """组装 MIME：alternative(text/html) [+ related(内嵌图)] [+ mixed(附件)]。"""
    has_inline = any(a.cid for a in msg.attachments)
    has_attach = any(not a.cid for a in msg.attachments)

    alt = MIMEMultipart("alternative")
    if msg.text:
        alt.attach(MIMEText(msg.text, "plain", "utf-8"))
    if msg.html:
        alt.attach(MIMEText(msg.html, "html", "utf-8"))

    if has_inline or has_attach:
        root = MIMEMultipart("mixed")
        if has_inline:
            related = MIMEMultipart("related")
            related.attach(alt)
            for a in msg.attachments:
                if a.cid:
                    img = MIMEImage(a.content, _subtype=a.mime.split("/")[-1], name=a.filename)
                    img.add_header("Content-ID", f"<{a.cid}>")
                    img.add_header("Content-Disposition", "inline", filename=a.filename)
                    related.attach(img)
            root.attach(related)
        else:
            root.attach(alt)
        for a in msg.attachments:
            if not a.cid:
                part = MIMEApplication(a.content, _subtype=a.mime.split("/")[-1], Name=a.filename)
                part["Content-Disposition"] = f'attachment; filename="{a.filename}"'
                root.attach(part)
        mime = root
    else:
        mime = alt

    mime["Subject"] = msg.subject
    mime["From"] = msg.from_addr
    mime["To"] = msg.to
    mime["Date"] = email.utils.formatdate(localtime=False)
    mime["Message-ID"] = email.utils.make_msgid()
    if msg.reply_to:
        mime["Reply-To"] = msg.reply_to
    for k, v in msg.headers.items():
        mime[k] = v
    return mime


def send_via_smtp(config: dict, msg: OutgoingMessage, timeout: float = 30.0) -> str:
    """通用 SMTP（SSL 465 或 STARTTLS 587）。返回 Message-ID。"""
    cfg = (config or {}).get("smtp", config)
    host = cfg.get("host", "")
    port = int(cfg.get("port", 587) or 587)
    user = cfg.get("user", "")
    password = cfg.get("password", "")
    if not host:
        raise SendError("SMTP 渠道缺少 host")

    mime = _build_mime(msg)
    message_id = mime["Message-ID"].strip()

    if port == 465:
        client = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
    else:
        client = smtplib.SMTP(host, port, timeout=timeout)
    try:
        client.ehlo()
        if port != 465:
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        if user and password:
            client.login(user, password)
        client.sendmail(_extract_addr(msg.from_addr), [msg.to], mime.as_string())
    except smtplib.SMTPException as e:
        raise SendError(f"SMTP 发送失败: {e}") from e
    finally:
        try:
            client.quit()
        except Exception:
            pass
    return message_id


def _extract_addr(addr: str) -> str:
    """'Name <a@b.c>' → 'a@b.c'。"""
    if "<" in addr and ">" in addr:
        return addr[addr.index("<") + 1 : addr.index(">")].strip()
    return addr.strip()


# ------------------------------------------------------------ 统一入口 ----

def send_message(channel_kind: str, config: dict, msg: OutgoingMessage) -> str:
    """按渠道分发。返回 provider message id（Resend id 或 SMTP Message-ID）。"""
    if channel_kind == "resend":
        return send_via_resend(config, msg)
    if channel_kind == "smtp":
        return send_via_smtp(config, msg)
    raise SendError(f"未知渠道类型: {channel_kind}")


def smtp_probe(config: dict, timeout: float = 10.0) -> None:
    """SMTP 连通性探测（登录+退出）。失败抛 SendError。"""
    cfg = (config or {}).get("smtp", config)
    host = cfg.get("host", "")
    port = int(cfg.get("port", 587) or 587)
    user, password = cfg.get("user", ""), cfg.get("password", "")
    try:
        if port == 465:
            client = smtplib.SMTP_SSL(host, port, timeout=timeout)
        else:
            client = smtplib.SMTP(host, port, timeout=timeout)
        try:
            client.ehlo()
            if port != 465:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if user and password:
                client.login(user, password)
        finally:
            client.quit()
    except (smtplib.SMTPException, OSError) as e:
        raise SendError(f"SMTP 连接失败: {e}") from e


def resend_probe(config: dict, timeout: float = 10.0) -> None:
    """Resend api_key 探测（GET /domains）。"""
    api_key = (config or {}).get("api_key", "")
    if not api_key:
        raise SendError("缺少 api_key")
    try:
        resp = httpx.get(
            "https://api.resend.com/domains",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
    except httpx.HTTPError as e:
        raise SendError(f"Resend 网络错误: {e}") from e
    if resp.status_code != 200:
        raise SendError(f"Resend HTTP {resp.status_code}: {resp.text[:200]}")


def build_unsubscribe_headers(unsubscribe_url: str | None = None) -> dict[str, str]:
    """合规头：List-Unsubscribe（有退订 URL 时）。"""
    if not unsubscribe_url:
        return {}
    return {
        "List-Unsubscribe": f"<{unsubscribe_url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
