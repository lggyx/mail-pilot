"""Resend webhook：svix 验签（免登录），事件落到收件人时间线。"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session as DBSession
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from ..db import get_db
from .. import models
from ..models import WebhookLog
from ..services import campaign_engine
from ..services.webhook_verify import WebhookVerificationError, verify_svix

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])
log = logging.getLogger(__name__)

# Resend 事件 → 内部事件类型（只关心对时间线有意义的）
EVENT_MAP = {
    "email.delivered": "delivered",
    "email.opened": "opened",
    "email.bounced": "bounced",
    "email.complained": "complained",
    "email.sent": "sent",
}


@router.post("/resend")
async def resend_webhook(
    request: Request,
    db: DBSession = Depends(get_db),
    svix_id: str = Header(""),
    svix_timestamp: str = Header(""),
    svix_signature: str = Header(""),
):
    body = await request.body()
    # 找出对应渠道的 webhook secret（渠道 config.webhook_secret）
    secret = _find_secret(db, svix_id)
    try:
        if secret:
            verify_svix(secret, svix_id, svix_timestamp, svix_signature, body)
        else:
            log.warning("resend webhook：未找到配置的 webhook_secret，跳过验签（开发环境）")
    except WebhookVerificationError as e:
        raise HTTPException(400, f"验签失败: {e}")

    import json

    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "请求体不是合法 JSON")

    event_type = payload.get("type", "")
    data = payload.get("data", {}) or {}
    message_id = data.get("email_id", "") or ""
    mapped = EVENT_MAP.get(event_type)
    handled = False
    if mapped:
        handled = campaign_engine.handle_provider_event(
            db, message_id, mapped,
            detail={"source": "resend", "type": event_type,
                    "to": data.get("to", [""])[0] if isinstance(data.get("to"), list) else data.get("to"),
                    "reason": (data.get("bounce") or {}).get("message", "") or (data.get("complaint") or {}).get("feedback_type", "")},
        )
    log_entry = WebhookLog(provider="resend", type=event_type, payload={"email_id": message_id}, handled=handled)
    db.add(log_entry)
    db.commit()
    return {"ok": True}


def _find_secret(db: DBSession, svix_id: str) -> str:
    """按渠道配置查找 webhook secret（多渠道时逐个尝试验签在 verify 层已兼容单 secret）。"""
    from sqlalchemy import or_

    channels = (
        db.query(models.Channel)
        .filter(models.Channel.kind == "resend")
        .all()
    )
    for ch in channels:
        secret = (ch.config or {}).get("webhook_secret", "")
        if secret:
            return secret
    return ""
