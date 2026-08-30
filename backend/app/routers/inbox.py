"""收件箱路由：IMAP 同步、列表、详情、批量操作、批量回复（回复走所选渠道发送并回写会话）。"""

from __future__ import annotations

from sqlalchemy.orm import Session as DBSession
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import selectinload

from .. import models
from ..auth import current_user
from ..db import get_db, SessionLocal
from ..routers.contacts import _message_dto
from ..services.imap_sync import IMAPError, imap_connect, scan_bounces, sync_inbox
from ..services.sender import OutgoingMessage, SendError, send_message
from ..services.renderer import render_body, make_text_version

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


@router.post("/sync")
def sync(db: DBSession = Depends(get_db), _: dict = Depends(current_user), channel_id: int = 0):
    """触发 IMAP 同步（收件 + 退信扫描）。channel_id 为空则同步所有配置了 IMAP 的 SMTP 渠道。"""
    q = db.query(models.Channel).filter(models.Channel.kind == "smtp")
    if channel_id:
        q = q.filter(models.Channel.id == channel_id)
    channels = q.all()
    if not channels:
        raise HTTPException(400, "没有可用的 IMAP 渠道：请先在渠道管理中配置 IMAP")
    results = []
    for ch in channels:
        try:
            inbox = sync_inbox(db, ch)
        except IMAPError as e:
            results.append({"channel": ch.name, "ok": False, "error": str(e)})
            continue
        bounce = {"scanned": 0, "applied": 0}
        try:
            bounce = scan_bounces(db, ch)
        except IMAPError as e:
            bounce = {"error": str(e)}
        results.append({"channel": ch.name, "ok": True, "inbox": inbox, "bounces": bounce})
    return {"data": results}


@router.get("")
def list_messages(db: DBSession = Depends(get_db), _: dict = Depends(current_user),
                  page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
                  q: str = "", filter: str = "all", contact_id: int = 0):
    query = db.query(models.Message).filter(models.Message.direction == "inbound")
    if filter == "unread":
        query = query.filter(models.Message.is_read.is_(False))
    elif filter == "archived":
        query = query.filter(models.Message.is_archived.is_(True))
    else:
        query = query.filter(models.Message.is_archived.is_(False))
    if contact_id:
        query = query.filter(models.Message.contact_id == contact_id)
    if q:
        query = query.filter(models.Message.subject.contains(q) | models.Message.text.contains(q)
                             | models.Message.from_email.contains(q))
    total = query.count()
    rows = (
        query.order_by(models.Message.received_at.desc().nullslast(), models.Message.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {"data": {"items": [_message_dto(m) for m in rows], "total": total,
                     "page": page, "page_size": page_size}}


@router.get("/unread-count")
def unread_count(db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    n = db.query(models.Message).filter(models.Message.direction == "inbound",
                                        models.Message.is_read.is_(False),
                                        models.Message.is_archived.is_(False)).count()
    return {"data": {"count": n}}


@router.get("/{message_id}")
def get_message(message_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    m = db.get(models.Message, message_id)
    if not m:
        raise HTTPException(404, "邮件不存在")
    if not m.is_read:
        m.is_read = True
        db.commit()
    # 同会话其他消息（同联系人）
    thread = []
    if m.contact_id:
        thread = (
            db.query(models.Message)
            .filter(models.Message.contact_id == m.contact_id)
            .order_by(models.Message.received_at.desc().nullslast(), models.Message.id.desc())
            .limit(100).all()
        )
    return {"data": {"message": _message_dto(m), "thread": [_message_dto(t) for t in thread]}}


class BatchIn(BaseModel):
    ids: list[int]
    action: str  # read / unread / archive / unarchive / delete / tag
    tag_ids: list[int] = []


@router.post("/batch")
def batch(body: BatchIn, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    if not body.ids:
        raise HTTPException(400, "未选择邮件")
    msgs = db.query(models.Message).filter(models.Message.id.in_(body.ids)).all()
    n = 0
    for m in msgs:
        if body.action == "read":
            m.is_read = True
        elif body.action == "unread":
            m.is_read = False
        elif body.action == "archive":
            m.is_archived = True
        elif body.action == "unarchive":
            m.is_archived = False
        elif body.action == "delete":
            db.delete(m)
        else:
            raise HTTPException(400, f"未知操作: {body.action}")
        n += 1
    db.commit()
    return {"data": {"affected": n}}


class ReplyIn(BaseModel):
    message_ids: list[int]
    subject: str
    body: str
    mode: str = "rich"
    channel_id: int | None = None


@router.post("/reply")
def reply(body: ReplyIn, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    """批量回复：对所选邮件的发件人（去重、排除退订/退信）发送，回写 outbound 会话。"""
    if not body.message_ids:
        raise HTTPException(400, "未选择要回复的邮件")
    msgs = db.query(models.Message).filter(models.Message.id.in_(body.message_ids)).all()
    if not msgs:
        raise HTTPException(404, "邮件不存在")

    channel = None
    if body.channel_id:
        channel = db.get(models.Channel, body.channel_id)
    if channel is None:
        channel = db.query(models.Channel).filter(models.Channel.is_default.is_(True)).first() \
            or db.query(models.Channel).first()
    if channel is None:
        raise HTTPException(400, "没有可用发送渠道")

    # 按发件人去重并聚合其联系人
    by_email: dict[str, models.Message] = {}
    for m in msgs:
        if m.direction == "inbound" and m.from_email:
            by_email.setdefault(m.from_email, m)
    results = []
    html = body.body if body.mode != "markdown" else render_body(body.body, "markdown", {})
    text = make_text_version(html)
    from_addr = (channel.config or {}).get("from", "")

    for email_addr, msg in by_email.items():
        contact = db.query(models.Contact).filter(models.Contact.email == email_addr).first()
        if contact and contact.status != "active":
            results.append({"email": email_addr, "ok": False, "error": f"联系人状态为 {contact.status}，已跳过"})
            continue
        out = OutgoingMessage(from_addr=from_addr, to=email_addr, subject=body.subject,
                              html=html, text=text)
        try:
            mid = send_message(channel.kind, channel.config or {}, out)
        except SendError as e:
            results.append({"email": email_addr, "ok": False, "error": str(e)})
            continue
        db.add(models.Message(
            direction="outbound", contact_id=contact.id if contact else None, channel_id=channel.id,
            message_id=mid, in_reply_to=msg.message_id,
            from_email=from_addr, to_email=email_addr, subject=body.subject,
            text=text, html=html, snippet=text[:200],
            sent_at=models.utcnow(),
        ))
        if contact:
            contact.last_email_at = models.utcnow()
        results.append({"email": email_addr, "ok": True, "message_id": mid})
    db.commit()
    return {"data": {"results": results}}


@router.post("/scan-bounces")
def trigger_bounce_scan(db: DBSession = Depends(get_db), _: dict = Depends(current_user),
                        channel_id: int = 0):
    q = db.query(models.Channel).filter(models.Channel.kind == "smtp")
    if channel_id:
        q = q.filter(models.Channel.id == channel_id)
    out = []
    for ch in q.all():
        try:
            out.append({"channel": ch.name, "ok": True, **scan_bounces(db, ch)})
        except IMAPError as e:
            out.append({"channel": ch.name, "ok": False, "error": str(e)})
    return {"data": out}
