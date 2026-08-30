"""活动路由：CRUD、收件人设定、发送计划/确认/暂停/继续/取消、逐收件人时间线。"""

from __future__ import annotations

from sqlalchemy.orm import Session as DBSession
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import selectinload

from .. import models
from ..auth import current_user
from ..db import get_db
from ..services import campaign_engine
from ..services.renderer import extract_variables

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignIn(BaseModel):
    name: str
    subject: str = ""
    mode: str = "rich"
    body: str = ""
    channel_id: int | None = None
    batch_size: int = 50
    rate_per_minute: int = 60
    max_retries: int = 3


class RecipientsIn(BaseModel):
    tag_ids: list[int] = []
    contact_ids: list[int] = []


def _dto(c: models.Campaign) -> dict:
    return {
        "id": c.id, "name": c.name, "subject": c.subject, "mode": c.mode, "body": c.body,
        "channel_id": c.channel_id, "status": c.status,
        "batch_size": c.batch_size, "rate_per_minute": c.rate_per_minute, "max_retries": c.max_retries,
        "plan": c.plan, "counts": c.counts or {},
        "variables": extract_variables(c.body + " " + c.subject),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "finished_at": c.finished_at.isoformat() if c.finished_at else None,
    }


def _get_campaign(db: DBSession, campaign_id: int) -> models.Campaign:
    c = (
        db.query(models.Campaign)
        .options(selectinload(models.Campaign.recipients), selectinload(models.Campaign.attachments))
        .filter(models.Campaign.id == campaign_id)
        .first()
    )
    if not c:
        raise HTTPException(404, "活动不存在")
    return c


@router.get("")
def list_campaigns(db: DBSession = Depends(get_db), _: dict = Depends(current_user),
                   status: str = "", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    q = db.query(models.Campaign).order_by(models.Campaign.id.desc())
    if status:
        q = q.filter(models.Campaign.status == status)
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return {"data": {"items": [_dto(c) for c in rows], "total": total, "page": page, "page_size": page_size}}


@router.post("")
def create_campaign(body: CampaignIn, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    if not body.name.strip():
        raise HTTPException(400, "活动名不能为空")
    if body.mode not in ("rich", "markdown", "html"):
        raise HTTPException(400, "mode 必须是 rich/markdown/html")
    c = models.Campaign(
        name=body.name.strip(), subject=body.subject, mode=body.mode, body=body.body,
        channel_id=body.channel_id, batch_size=max(1, body.batch_size),
        rate_per_minute=max(1, body.rate_per_minute), max_retries=max(0, body.max_retries),
    )
    db.add(c)
    db.commit()
    return {"data": _dto(c)}


@router.get("/{campaign_id}")
def get_campaign(campaign_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    return {"data": _dto(_get_campaign(db, campaign_id))}


@router.put("/{campaign_id}")
def update_campaign(campaign_id: int, body: CampaignIn, db: DBSession = Depends(get_db),
                    _: dict = Depends(current_user)):
    c = _get_campaign(db, campaign_id)
    if c.status in ("sending", "completed", "cancelled"):
        raise HTTPException(400, f"当前状态（{c.status}）不可编辑")
    c.name = body.name.strip() or c.name
    c.subject = body.subject
    c.mode = body.mode
    c.body = body.body
    c.channel_id = body.channel_id
    c.batch_size = max(1, body.batch_size)
    c.rate_per_minute = max(1, body.rate_per_minute)
    c.max_retries = max(0, body.max_retries)
    db.commit()
    return {"data": _dto(c)}


@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    c = db.get(models.Campaign, campaign_id)
    if not c:
        raise HTTPException(404, "活动不存在")
    if c.status == "sending":
        raise HTTPException(400, "发送中的活动不能删除，请先暂停/取消")
    db.delete(c)
    db.commit()
    return {"data": {"ok": True}}


@router.put("/{campaign_id}/recipients")
def set_recipients(campaign_id: int, body: RecipientsIn, db: DBSession = Depends(get_db),
                   _: dict = Depends(current_user)):
    c = _get_campaign(db, campaign_id)
    if c.status in ("sending", "completed", "cancelled"):
        raise HTTPException(400, f"当前状态（{c.status}）不可修改收件人")
    if not body.tag_ids and not body.contact_ids:
        raise HTTPException(400, "请按标签或指定联系人选择收件人")
    stats = campaign_engine.set_recipients(db, c, tag_ids=body.tag_ids, contact_ids=body.contact_ids)
    return {"data": stats}


@router.post("/{campaign_id}/plan")
def plan(campaign_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    c = _get_campaign(db, campaign_id)
    return {"data": campaign_engine.build_plan(db, c)}


@router.post("/{campaign_id}/confirm")
def confirm(campaign_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    c = _get_campaign(db, campaign_id)
    try:
        campaign_engine.confirm_campaign(db, c)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"data": _dto(c)}


@router.post("/{campaign_id}/pause")
def pause(campaign_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    campaign_engine.pause_campaign(db, _get_campaign(db, campaign_id))
    return {"data": {"ok": True}}


@router.post("/{campaign_id}/resume")
def resume(campaign_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    try:
        campaign_engine.resume_campaign(db, _get_campaign(db, campaign_id))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"data": {"ok": True}}


@router.post("/{campaign_id}/cancel")
def cancel(campaign_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    campaign_engine.cancel_campaign(db, _get_campaign(db, campaign_id))
    return {"data": {"ok": True}}


@router.get("/{campaign_id}/recipients")
def list_recipients(campaign_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user),
                    status: str = "", page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    c = _get_campaign(db, campaign_id)
    q = db.query(models.CampaignRecipient).filter(models.CampaignRecipient.campaign_id == c.id)
    if status:
        q = q.filter(models.CampaignRecipient.status == status)
    total = q.count()
    rows = q.order_by(models.CampaignRecipient.id).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "data": {
            "items": [_recipient_dto(r) for r in rows],
            "total": total, "page": page, "page_size": page_size, "counts": c.counts or {},
        }
    }


def _recipient_dto(r: models.CampaignRecipient) -> dict:
    return {
        "id": r.id, "email": r.email, "name": r.name, "status": r.status,
        "attempts": r.attempts, "error": r.error,
        "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        "delivered_at": r.delivered_at.isoformat() if r.delivered_at else None,
        "opened_at": r.opened_at.isoformat() if r.opened_at else None,
        "bounced_at": r.bounced_at.isoformat() if r.bounced_at else None,
        "complained_at": r.complained_at.isoformat() if r.complained_at else None,
    }


@router.get("/{campaign_id}/recipients/{recipient_id}/events")
def recipient_events(campaign_id: int, recipient_id: int, db: DBSession = Depends(get_db),
                     _: dict = Depends(current_user)):
    r = (
        db.query(models.CampaignRecipient)
        .options(selectinload(models.CampaignRecipient.events))
        .filter(models.CampaignRecipient.id == recipient_id,
                models.CampaignRecipient.campaign_id == campaign_id)
        .first()
    )
    if not r:
        raise HTTPException(404, "收件人不存在")
    events = sorted(r.events, key=lambda e: e.created_at or 0)
    return {
        "data": {
            "recipient": _recipient_dto(r),
            "events": [
                {"id": e.id, "type": e.type,
                 "detail": e.detail, "created_at": e.created_at.isoformat() if e.created_at else None}
                for e in events
            ],
        }
    }
