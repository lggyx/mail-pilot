"""渠道 CRUD 与连通性测试（Resend / IMAP+SMTP）。"""

from __future__ import annotations

from sqlalchemy.orm import Session as DBSession
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import models
from ..auth import current_user
from ..db import get_db
from ..services.sender import SendError, resend_probe, send_message, smtp_probe, OutgoingMessage

router = APIRouter(prefix="/api/channels", tags=["channels"])


class ChannelIn(BaseModel):
    kind: str
    name: str
    config: dict = {}
    is_default: bool = False


def _dto(c: models.Channel, *, mask_secret: bool = True) -> dict:
    config = dict(c.config or {})
    if mask_secret:
        if config.get("api_key"):
            config["api_key"] = config["api_key"][:6] + "***" if len(config["api_key"]) > 6 else "***"
        smtp = config.get("smtp")
        if isinstance(smtp, dict) and smtp.get("password"):
            smtp = {**smtp, "password": "***"}
        imap = config.get("imap")
        if isinstance(imap, dict) and imap.get("password"):
            imap = {**imap, "password": "***"}
        config = {**config, "smtp": smtp, "imap": imap}
    return {
        "id": c.id, "kind": c.kind, "name": c.name, "config": config,
        "is_default": c.is_default, "status": c.status,
        "last_error": c.last_error,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _merge_config(existing: dict, incoming: dict) -> dict:
    """掩码值（'***' 结尾）不覆盖真实密钥。"""
    merged = {**existing, **{k: v for k, v in incoming.items() if v is not None}}
    for section in ("smtp", "imap"):
        old, new = existing.get(section), incoming.get(section)
        if isinstance(old, dict) and isinstance(new, dict):
            merged[section] = {**old, **{k: v for k, v in new.items() if v != "***"}}
    if incoming.get("api_key") and str(incoming["api_key"]).endswith("***"):
        merged["api_key"] = existing.get("api_key", "")
    return merged


@router.get("")
def list_channels(db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    rows = db.query(models.Channel).order_by(models.Channel.id).all()
    return {"data": [_dto(c) for c in rows]}


@router.post("")
def create_channel(body: ChannelIn, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    if body.kind not in ("resend", "smtp"):
        raise HTTPException(400, "kind 必须是 resend 或 smtp")
    if not body.name.strip():
        raise HTTPException(400, "名称不能为空")
    c = models.Channel(kind=body.kind, name=body.name.strip(), config=body.config)
    if body.is_default:
        db.query(models.Channel).update({models.Channel.is_default: False})
    c.is_default = body.is_default
    db.add(c)
    db.commit()
    return {"data": _dto(c)}


@router.put("/{channel_id}")
def update_channel(channel_id: int, body: ChannelIn, db: DBSession = Depends(get_db),
                   _: dict = Depends(current_user)):
    c = db.get(models.Channel, channel_id)
    if not c:
        raise HTTPException(404, "渠道不存在")
    c.name = body.name.strip() or c.name
    c.config = _merge_config(c.config or {}, body.config or {})
    if body.is_default:
        db.query(models.Channel).update({models.Channel.is_default: False})
        c.is_default = True
    db.commit()
    return {"data": _dto(c)}


@router.delete("/{channel_id}")
def delete_channel(channel_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    c = db.get(models.Channel, channel_id)
    if c:
        db.delete(c)
        db.commit()
    return {"data": {"ok": True}}


@router.post("/{channel_id}/test")
def test_channel(channel_id: int, to: str = "", db: DBSession = Depends(get_db),
                 _: dict = Depends(current_user)):
    """连通性测试；带 to 参数可发测试邮件到该地址。"""
    c = db.get(models.Channel, channel_id)
    if not c:
        raise HTTPException(404, "渠道不存在")
    try:
        if c.kind == "resend":
            resend_probe(c.config or {})
            if to:
                send_message("resend", c.config or {}, OutgoingMessage(
                    from_addr=(c.config or {}).get("from", ""), to=to,
                    subject="mail-pilot 渠道测试", html="<p>这是一封渠道连通性测试邮件。</p>",
                    text="这是一封渠道连通性测试邮件。"))
        else:
            smtp_probe(c.config or {})
            if to:
                send_message("smtp", c.config or {}, OutgoingMessage(
                    from_addr=(c.config or {}).get("from", ""), to=to,
                    subject="mail-pilot 渠道测试", html="<p>这是一封渠道连通性测试邮件。</p>",
                    text="这是一封渠道连通性测试邮件。"))
    except SendError as e:
        c.status, c.last_error = "error", str(e)
        db.commit()
        return {"data": {"ok": False, "error": str(e)}}
    c.status, c.last_error = "ok", ""
    db.commit()
    return {"data": {"ok": True}}
