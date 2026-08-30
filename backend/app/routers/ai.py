"""AI 路由：代写/改写/体检/退信归因/摘要/草拟回复 + 配置测试。

AI 请求为长耗时操作：处理函数用线程池（sync def）执行，不阻塞事件循环。
"""

from __future__ import annotations

import asyncio

from sqlalchemy.orm import Session as DBSession
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import models
from ..auth import current_user
from ..db import get_db
from ..services import ai_tasks
from ..services.ai_adapter import AIError, chat, list_models
from ..services.ai_tasks import CheckupResult, local_checkup

router = APIRouter(prefix="/api/ai", tags=["ai"])


def _active_config(db: DBSession) -> models.AIConfig:
    cfg = db.query(models.AIConfig).filter(models.AIConfig.is_active.is_(True)).first()
    if not cfg:
        raise HTTPException(400, "未配置 AI：请先在设置页添加并激活一个 AI 配置")
    return cfg


def _cfg_dict(c: models.AIConfig) -> dict:
    return {"base_url": c.base_url, "api_key": c.api_key, "model": c.model}


def _map_ai_error(e: AIError) -> HTTPException:
    code = {"auth": 401, "rate_limit": 429, "bad_request": 400}.get(e.kind, 502)
    return HTTPException(code, str(e))


class GenerateIn(BaseModel):
    intent: str
    tone: str = "专业友好"
    mode: str = "rich"


@router.post("/generate")
def generate(body: GenerateIn, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    cfg = _active_config(db)
    try:
        return {"data": ai_tasks.ai_generate(_cfg_dict(cfg), intent=body.intent, tone=body.tone, mode=body.mode)}
    except AIError as e:
        raise _map_ai_error(e)


class RewriteIn(BaseModel):
    subject: str = ""
    body: str = ""
    instruction: str = ""
    mode: str = "rich"


@router.post("/rewrite")
def rewrite(body: RewriteIn, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    cfg = _active_config(db)
    try:
        return {"data": ai_tasks.ai_rewrite(_cfg_dict(cfg), subject=body.subject, body=body.body,
                                            instruction=body.instruction, mode=body.mode)}
    except AIError as e:
        raise _map_ai_error(e)


class CheckupIn(BaseModel):
    subject: str = ""
    html: str = ""


@router.post("/checkup")
def checkup(body: CheckupIn, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    """发送前体检：本地规则 + AI 复核合并。AI 不可用时降级为纯本地结果。"""
    local = local_checkup(body.subject, body.html)
    try:
        cfg = _active_config(db)
    except HTTPException:
        return {"data": {**local.as_dict(), "ai_available": False}}
    try:
        result = ai_tasks.ai_checkup(_cfg_dict(cfg), subject=body.subject, html=body.html, local=local)
    except AIError as e:
        merged = local.as_dict()
        merged["ai_error"] = f"{e.kind}: {e}"
        merged["ai_available"] = False
        return {"data": merged}
    return {"data": result}


class AnalyzeBouncesIn(BaseModel):
    campaign_id: int


@router.post("/analyze-bounces")
def analyze_bounces(body: AnalyzeBouncesIn, db: DBSession = Depends(get_db),
                    _: dict = Depends(current_user)):
    """发送后归因：用 bounced/complained 收件人与内容生成分析与整改版。"""
    campaign = db.get(models.Campaign, body.campaign_id)
    if not campaign:
        raise HTTPException(404, "活动不存在")
    recipients = (
        db.query(models.CampaignRecipient)
        .filter(models.CampaignRecipient.campaign_id == campaign.id,
                models.CampaignRecipient.status.in_(("bounced", "complained")))
        .all()
    )
    bounced = [{"email": r.email, "kind": "bounced", "error": r.error} for r in recipients if r.status == "bounced"]
    complained = [{"email": r.email, "kind": "complained", "error": r.error} for r in recipients if r.status == "complained"]
    if not bounced and not complained:
        raise HTTPException(400, "该活动没有退信或被标垃圾的记录，无需归因")
    cfg = _active_config(db)
    try:
        data = ai_tasks.ai_analyze_bounces(
            _cfg_dict(cfg), subject=campaign.subject,
            html=campaign.body, bounced=bounced, complained=complained,
        )
    except AIError as e:
        raise _map_ai_error(e)
    return {"data": {**data, "bounced_count": len(bounced), "complained_count": len(complained),
                     "excluded_emails": [r["email"] for r in bounced + complained]}}


class MessagesIn(BaseModel):
    message_ids: list[int] = []
    instruction: str = ""


@router.post("/summarize")
def summarize(body: MessagesIn, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    msgs = db.query(models.Message).filter(models.Message.id.in_(body.message_ids)).all() if body.message_ids else []
    if not msgs:
        raise HTTPException(400, "请选择要摘要的邮件")
    data = [
        {"direction": m.direction, "from_email": m.from_email,
         "text": m.text or (m.html or "")}
        for m in msgs
    ]
    cfg = _active_config(db)
    try:
        return {"data": {"summary": ai_tasks.ai_summarize(_cfg_dict(cfg), messages=data)}}
    except AIError as e:
        raise _map_ai_error(e)


@router.post("/draft-reply")
def draft_reply(body: MessagesIn, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    msgs = db.query(models.Message).filter(models.Message.id.in_(body.message_ids)).all() if body.message_ids else []
    if not msgs:
        raise HTTPException(400, "请选择要回复的邮件")
    data = [
        {"direction": m.direction, "from_email": m.from_email,
         "text": m.text or (m.html or "")}
        for m in msgs
    ]
    cfg = _active_config(db)
    try:
        return {"data": ai_tasks.ai_draft_reply(_cfg_dict(cfg), messages=data, instruction=body.instruction)}
    except AIError as e:
        raise _map_ai_error(e)
