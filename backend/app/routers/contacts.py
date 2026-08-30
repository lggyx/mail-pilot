"""联系人 / 标签 / 导入 / 会话聚合路由。"""

from __future__ import annotations

from sqlalchemy.orm import Session as DBSession
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from .. import models
from ..auth import current_user
from ..db import get_db
from ..services.importer import ImportReport, import_contacts, parse_rows
from ..utils.email_addr import is_valid_email, normalize_email

router = APIRouter(prefix="/api", tags=["contacts"])


# ---------------------------------------------------------------- 查询 ----

@router.get("/contacts")
def list_contacts(
    db: DBSession = Depends(get_db),
    _: dict = Depends(current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    q: str = "",
    status: str = "",
    tag_id: int = 0,
):
    query = db.query(models.Contact)
    if q:
        query = query.filter(models.Contact.email.contains(q) | models.Contact.name.contains(q))
    if status:
        query = query.filter(models.Contact.status == status)
    if tag_id:
        query = query.filter(models.Contact.tags.any(models.Tag.id == tag_id))
    total = query.count()
    rows = (
        query.order_by(models.Contact.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "data": {
            "items": [_contact_dto(c) for c in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    }


def _contact_dto(c: models.Contact) -> dict:
    return {
        "id": c.id, "email": c.email, "name": c.name, "status": c.status,
        "source": c.source, "note": c.note, "created_at": c.created_at.isoformat() if c.created_at else None,
        "last_email_at": c.last_email_at.isoformat() if c.last_email_at else None,
        "tags": [{"id": t.id, "name": t.name, "color": t.color} for t in c.tags],
    }


@router.get("/contacts/{contact_id}")
def get_contact(contact_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    c = db.get(models.Contact, contact_id)
    if not c:
        raise HTTPException(404, "联系人不存在")
    msgs = (
        db.query(models.Message)
        .filter(models.Message.contact_id == contact_id)
        .order_by(models.Message.received_at.desc().nullslast(), models.Message.id.desc())
        .limit(100)
        .all()
    )
    campaigns = (
        db.query(models.CampaignRecipient, models.Campaign)
        .join(models.Campaign, models.Campaign.id == models.CampaignRecipient.campaign_id)
        .filter(models.CampaignRecipient.contact_id == contact_id)
        .order_by(models.CampaignRecipient.id.desc())
        .limit(20)
        .all()
    )
    return {
        "data": {
            "contact": _contact_dto(c),
            "thread": [_message_dto(m) for m in msgs],
            "campaign_history": [
                {
                    "campaign_id": cr.campaign_id, "campaign_name": cp.name,
                    "status": cr.status, "sent_at": cr.sent_at.isoformat() if cr.sent_at else None,
                    "bounced_at": cr.bounced_at.isoformat() if cr.bounced_at else None,
                    "complained_at": cr.complained_at.isoformat() if cr.complained_at else None,
                }
                for cr, cp in campaigns
            ],
        }
    }


def _message_dto(m: models.Message) -> dict:
    return {
        "id": m.id, "direction": m.direction, "subject": m.subject, "snippet": m.snippet,
        "text": m.text, "html": m.html, "from_email": m.from_email, "from_name": m.from_name,
        "to_email": m.to_email, "is_read": m.is_read, "is_archived": m.is_archived,
        "received_at": m.received_at.isoformat() if m.received_at else None,
        "sent_at": m.sent_at.isoformat() if m.sent_at else None,
        "contact_id": m.contact_id,
    }


class ContactUpdate(BaseModel):
    name: str | None = None
    note: str | None = None
    status: str | None = None
    tag_ids: list[int] | None = None


@router.put("/contacts/{contact_id}")
def update_contact(contact_id: int, body: ContactUpdate, db: DBSession = Depends(get_db),
                   _: dict = Depends(current_user)):
    c = db.get(models.Contact, contact_id)
    if not c:
        raise HTTPException(404, "联系人不存在")
    if body.name is not None:
        c.name = body.name
    if body.note is not None:
        c.note = body.note
    if body.status is not None:
        if body.status not in ("active", "unsubscribed", "bounced", "complained"):
            raise HTTPException(400, "非法状态")
        c.status = body.status
    if body.tag_ids is not None:
        tags = db.query(models.Tag).filter(models.Tag.id.in_(body.tag_ids)).all()
        c.tags = tags
    db.commit()
    return {"data": _contact_dto(c)}


@router.delete("/contacts/{contact_id}")
def delete_contact(contact_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    c = db.get(models.Contact, contact_id)
    if not c:
        raise HTTPException(404, "联系人不存在")
    db.delete(c)
    db.commit()
    return {"data": {"ok": True}}


# ---------------------------------------------------------------- 标签 ----

@router.get("/tags")
def list_tags(db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    tags = db.query(models.Tag).order_by(models.Tag.name).all()
    return {"data": [{"id": t.id, "name": t.name, "color": t.color} for t in tags]}


class TagCreate(BaseModel):
    name: str
    color: str = "#ffb066"


@router.post("/tags")
def create_tag(body: TagCreate, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "标签名不能为空")
    tag = db.query(models.Tag).filter(models.Tag.name == name).first()
    if tag:
        return {"data": {"id": tag.id, "name": tag.name, "color": tag.color}}
    tag = models.Tag(name=name, color=body.color)
    db.add(tag)
    db.commit()
    return {"data": {"id": tag.id, "name": tag.name, "color": tag.color}}


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    tag = db.get(models.Tag, tag_id)
    if tag:
        db.delete(tag)
        db.commit()
    return {"data": {"ok": True}}


# ---------------------------------------------------------------- 导入 ----

@router.post("/contacts/import")
async def import_contacts_api(
    file: UploadFile | None = File(None),
    text: str = Form(""),
    fmt: str = Form(""),
    tag_ids: str = Form("[]"),  # JSON 数组字符串
    db: DBSession = Depends(get_db),
    _: dict = Depends(current_user),
):
    """多格式导入：multipart 文件（csv/xlsx/json/txt 按扩展名或 fmt 指定）或粘贴文本（fmt=paste）。"""
    import json as _json

    if file is None and not text.strip():
        raise HTTPException(400, "请上传文件或粘贴文本")

    content: bytes | str
    if file is not None:
        content = await file.read()
        fmt = fmt or (file.filename or "").rsplit(".", 1)[-1].lower()
        if fmt not in ("csv", "xlsx", "json", "txt"):
            raise HTTPException(400, f"不支持的文件格式: {fmt}（支持 csv/xlsx/json/txt）")
    else:
        content = text
        fmt = fmt or "paste"

    try:
        rows = parse_rows(content, fmt)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"解析失败: {e}")

    try:
        ids = [int(i) for i in (_json.loads(tag_ids) or [])]
    except Exception:
        ids = []

    report = import_contacts(db, rows, tag_ids=ids)
    return {"data": report.as_dict()}


# ---------------------------------------------------------------- 预览 ----

class PreviewRequest(BaseModel):
    text: str
    fmt: str = "paste"


@router.post("/contacts/import/preview")
def import_preview(body: PreviewRequest, _: dict = Depends(current_user)):
    """粘贴内容预览：返回解析出的条目数与无效行样例（不入库）。"""
    try:
        rows = parse_rows(body.text, body.fmt)
    except Exception as e:
        raise HTTPException(400, f"解析失败: {e}")
    valid = [r for r in rows if r.valid]
    invalid = [{"raw": r.email or r.reason, "reason": r.reason} for r in rows if not r.valid]
    return {"data": {"total": len(rows), "valid": len(valid), "invalid": invalid[:20]}}
