"""设置路由：AI 配置 CRUD/测试/激活、常规设置、概览统计。"""

from __future__ import annotations

from sqlalchemy.orm import Session as DBSession
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import models
from ..auth import current_user
from ..db import get_db
from ..services.ai_adapter import AIError, chat, ChatMessage, list_models

router = APIRouter(prefix="/api", tags=["settings"])


# ------------------------------------------------------------ AI 配置 ----

class AIConfigIn(BaseModel):
    name: str
    base_url: str
    api_key: str = ""
    model: str


def _dto(c: models.AIConfig, *, mask: bool = True) -> dict:
    key = c.api_key or ""
    return {
        "id": c.id, "name": c.name, "base_url": c.base_url,
        "api_key": (key[:6] + "***") if mask and len(key) > 6 else ("***" if mask and key else key),
        "model": c.model, "is_active": c.is_active,
        "last_test_at": c.last_test_at.isoformat() if c.last_test_at else None,
        "last_test_ok": c.last_test_ok,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _merge_key(existing: models.AIConfig, incoming_key: str) -> str:
    return existing.api_key if incoming_key.endswith("***") else incoming_key


@router.get("/ai-configs")
def list_ai_configs(db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    rows = db.query(models.AIConfig).order_by(models.AIConfig.id).all()
    return {"data": [_dto(c) for c in rows]}


@router.post("/ai-configs")
def create_ai_config(body: AIConfigIn, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    if not body.name.strip() or not body.base_url.strip() or not body.model.strip():
        raise HTTPException(400, "名称 / base_url / model 均必填")
    c = models.AIConfig(name=body.name.strip(), base_url=body.base_url.strip().rstrip("/"),
                        api_key=body.api_key, model=body.model.strip())
    db.add(c)
    db.commit()
    return {"data": _dto(c)}


@router.put("/ai-configs/{config_id}")
def update_ai_config(config_id: int, body: AIConfigIn, db: DBSession = Depends(get_db),
                     _: dict = Depends(current_user)):
    c = db.get(models.AIConfig, config_id)
    if not c:
        raise HTTPException(404, "配置不存在")
    c.name = body.name.strip() or c.name
    c.base_url = body.base_url.strip().rstrip("/")
    c.api_key = _merge_key(c, body.api_key)
    c.model = body.model.strip() or c.model
    db.commit()
    return {"data": _dto(c)}


@router.delete("/ai-configs/{config_id}")
def delete_ai_config(config_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    c = db.get(models.AIConfig, config_id)
    if c:
        db.delete(c)
        db.commit()
    return {"data": {"ok": True}}


@router.post("/ai-configs/{config_id}/activate")
def activate_ai_config(config_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    c = db.get(models.AIConfig, config_id)
    if not c:
        raise HTTPException(404, "配置不存在")
    db.query(models.AIConfig).update({models.AIConfig.is_active: False})
    c.is_active = True
    db.commit()
    return {"data": {"ok": True}}


@router.post("/ai-configs/{config_id}/test")
def test_ai_config(config_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    """连通性测试：先探测 /models（可空），再发一条最小对话。"""
    from datetime import datetime

    c = db.get(models.AIConfig, config_id)
    if not c:
        raise HTTPException(404, "配置不存在")
    cfg = {"base_url": c.base_url, "api_key": c.api_key, "model": c.model}
    c.last_test_at = datetime.utcnow()
    try:
        chat(cfg, [ChatMessage("user", "回复：ok")], temperature=0, timeout=30)
    except AIError as e:
        c.last_test_ok = False
        db.commit()
        return {"data": {"ok": False, "error": f"{e.kind}: {e}"}}
    c.last_test_ok = True
    db.commit()
    models_list = list_models(cfg)
    return {"data": {"ok": True, "models": models_list}}


@router.post("/ai-configs/{config_id}/models")
def fetch_models(config_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    c = db.get(models.AIConfig, config_id)
    if not c:
        raise HTTPException(404, "配置不存在")
    return {"data": {"models": list_models({"base_url": c.base_url, "api_key": c.api_key, "model": c.model})}}


# ------------------------------------------------------------ 常规设置 ----

class SettingIn(BaseModel):
    key: str
    value: dict


@router.get("/settings")
def get_settings(db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    rows = db.query(models.AppSetting).all()
    return {"data": {r.key: r.value for r in rows}}


@router.put("/settings")
def put_setting(body: SettingIn, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    row = db.get(models.AppSetting, body.key)
    if row:
        row.value = body.value
    else:
        db.add(models.AppSetting(key=body.key, value=body.value))
    db.commit()
    return {"data": {"ok": True}}


# ------------------------------------------------------------ 概览 ----

@router.get("/dashboard/stats")
def dashboard_stats(db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    contacts_total = db.query(models.Contact).count()
    contact_status: dict[str, int] = {}
    for st in ("active", "unsubscribed", "bounced", "complained"):
        contact_status[st] = db.query(models.Contact).filter(models.Contact.status == st).count()

    campaigns_total = db.query(models.Campaign).count()
    campaigns_sending = db.query(models.Campaign).filter(models.Campaign.status == "sending").count()

    rec_counts: dict[str, int] = {}
    for st in ("sent", "delivered", "opened", "bounced", "complained", "failed", "skipped", "pending"):
        rec_counts[st] = db.query(models.CampaignRecipient).filter(models.CampaignRecipient.status == st).count()

    unread = db.query(models.Message).filter(
        models.Message.direction == "inbound", models.Message.is_read.is_(False),
        models.Message.is_archived.is_(False)).count()

    delivered = rec_counts.get("delivered", 0) + rec_counts.get("opened", 0)
    sent = rec_counts.get("sent", 0) + delivered
    return {
        "data": {
            "contacts": {"total": contacts_total, **contact_status},
            "campaigns": {"total": campaigns_total, "sending": campaigns_sending},
            "delivery": {
                "sent": sent, "delivered": delivered,
                "opened": rec_counts.get("opened", 0),
                "bounced": rec_counts.get("bounced", 0),
                "complained": rec_counts.get("complained", 0),
                "pending": rec_counts.get("pending", 0),
                "deliver_rate": round(delivered / sent * 100, 1) if sent else None,
                "open_rate": round(rec_counts.get("opened", 0) / delivered * 100, 1) if delivered else None,
            },
            "inbox": {"unread": unread},
        }
    }
