"""活动引擎：生成发送计划 → 确认 → 调度推进（令牌桶限速 + 指数退避重试）→ 状态机与事件。

状态机规则独立成纯函数（apply_event），便于测试。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, selectinload, sessionmaker

from .. import models
from ..models import Campaign, CampaignRecipient, Contact, RecipientEvent, utcnow
from .renderer import render_body, make_text_version
from .sender import OutgoingAttachment, OutgoingMessage, SendError, send_message
from .throttle import GlobalPacer, TokenBucket
from ..config import settings

log = logging.getLogger(__name__)

# 发送中的活动 → 令牌桶缓存（进程内）
_buckets: dict[int, TokenBucket] = {}
_pacer = GlobalPacer(min_interval=1.0)
_tick_lock = threading.Lock()


# ------------------------------------------------------------ 状态机 ----

def apply_event(recipient: CampaignRecipient, event_type: str, at: datetime | None = None) -> bool:
    """按时间线状态机迁移收件人状态。返回是否发生迁移（写入字段由调用方持久化）。

    sent → delivered → opened；bounced/complained 可在 sent 及之后到达；重复事件幂等。
    """
    at = at or utcnow()
    st, et = recipient.status, event_type

    def _set(status: str, field_name: str) -> bool:
        if getattr(recipient, field_name) is None:
            setattr(recipient, field_name, at)
        recipient.status = status
        return True

    if st in ("pending", "sending", "failed"):
        return False  # 送达类事件不应先于 sent（Resend 保证顺序；SMTP 退信走 bounce_scan）
    if et == "delivered" and st == "sent":
        return _set("delivered", "delivered_at")
    if et == "opened" and st in ("sent", "delivered", "opened"):
        return _set("opened", "opened_at")
    if et == "bounced" and st in ("sent", "delivered", "opened"):
        return _set("bounced", "bounced_at")
    if et == "complained" and st in ("sent", "delivered", "opened", "bounced"):
        return _set("complained", "complained_at")
    return False


def record_event(db: Session, recipient: CampaignRecipient, event_type: str, detail: dict | None = None) -> None:
    event = RecipientEvent(recipient_id=recipient.id, type=event_type, detail=detail or {})
    db.add(event)
    # 同步关系集合（expire_on_commit=False 时懒加载不会自动感知新事件）
    if recipient.events is not None:
        recipient.events.append(event)


def sync_contact_status(db: Session, recipient: CampaignRecipient) -> None:
    """bounced/complained 回写联系人状态（列表质量随事件自动降级）。"""
    if not recipient.contact_id:
        return
    contact = db.get(Contact, recipient.contact_id)
    if contact and recipient.status in ("bounced", "complained"):
        contact.status = recipient.status


# ------------------------------------------------------------ 计划 ----

def set_recipients(db: Session, campaign: Campaign, *, tag_ids: list[int] | None = None,
                   contact_ids: list[int] | None = None) -> dict:
    """设定收件人：按标签/指定联系人，排除退订/退信/投诉与活动内重复，返回预览统计。"""
    q = db.query(Contact).filter(Contact.status == "active")
    if tag_ids:
        q = q.filter(Contact.tags.any(models.Tag.id.in_(tag_ids)))
    if contact_ids:
        q = q.filter(Contact.id.in_(contact_ids))
    contacts = q.all()

    existing = {r.email: r for r in campaign.recipients}
    excluded_blocked = 0
    added = 0
    for c in contacts:
        if c.email in existing:
            continue
        db.add(CampaignRecipient(campaign_id=campaign.id, contact_id=c.id, email=c.email, name=c.name))
        existing[c.email] = None
        added += 1
    db.commit()
    db.refresh(campaign)

    blocked = db.query(Contact).filter(Contact.status != "active")
    if tag_ids:
        blocked = blocked.filter(Contact.tags.any(models.Tag.id.in_(tag_ids)))
    if contact_ids:
        blocked = blocked.filter(Contact.id.in_(contact_ids))
    excluded_blocked = blocked.count()

    return {"contacts_matched": len(contacts), "recipients_added": added,
            "recipients_total": len(campaign.recipients), "excluded_blocked": excluded_blocked}


def build_plan(db: Session, campaign: Campaign) -> dict:
    """发送计划：人数/批次/预计耗时/渠道/排除摘要。写回 campaign.plan。"""
    db.refresh(campaign)
    recipients = campaign.recipients
    total = sum(1 for r in recipients if r.status == "pending")
    rate = max(1, campaign.rate_per_minute)
    batches = max(1, -(-total // max(1, campaign.batch_size)))
    est_minutes = round(total / rate + (batches - 1) * 0.5, 1) if total else 0.0

    channel = db.get(models.Channel, campaign.channel_id) if campaign.channel_id else None
    by_status: dict[str, int] = {}
    for r in recipients:
        by_status[r.status] = by_status.get(r.status, 0) + 1

    plan = {
        "total": total,
        "by_status": by_status,
        "batch_size": campaign.batch_size,
        "rate_per_minute": rate,
        "batches": batches,
        "estimated_minutes": est_minutes,
        "channel": {"id": channel.id, "name": channel.name, "kind": channel.kind} if channel else None,
        "subject": campaign.subject,
        "generated_at": utcnow().isoformat(),
    }
    campaign.plan = plan
    db.commit()
    return plan


def confirm_campaign(db: Session, campaign: Campaign) -> None:
    """确认计划：draft/planned/paused → sending。"""
    if campaign.status == "sending":
        return
    if not any(r.status == "pending" for r in campaign.recipients):
        raise ValueError("没有待发送的收件人，请先设定收件人")
    if not campaign.channel_id:
        raise ValueError("请先选择发送渠道")
    campaign.status = "sending"
    campaign.started_at = campaign.started_at or utcnow()
    campaign.finished_at = None
    db.commit()
    _buckets.pop(campaign.id, None)


def pause_campaign(db: Session, campaign: Campaign) -> None:
    if campaign.status == "sending":
        campaign.status = "paused"
        db.commit()


def resume_campaign(db: Session, campaign: Campaign) -> None:
    if campaign.status == "paused":
        campaign.status = "sending"
        db.commit()
        _buckets.pop(campaign.id, None)


def cancel_campaign(db: Session, campaign: Campaign) -> None:
    was_sending = campaign.status in ("sending", "paused")
    for r in campaign.recipients:
        if r.status in ("pending", "failed", "sending"):
            r.status = "skipped"
            record_event(db, r, "skipped", {"reason": "活动被取消"})
    campaign.status = "cancelled"
    if was_sending:
        campaign.finished_at = utcnow()
    db.commit()
    _buckets.pop(campaign.id, None)


# ------------------------------------------------------------ 推进 ----

def _personalize_variables(recipient: CampaignRecipient) -> dict[str, str]:
    return {"email": recipient.email, "name": recipient.name or (recipient.email.split("@")[0])}


def _process_recipient(db: Session, campaign: Campaign, recipient: CampaignRecipient) -> None:
    """发送单个收件人：渲染 → 渠道发送 → 状态/事件；失败进退避重试。"""
    channel = db.get(models.Channel, campaign.channel_id)
    if channel is None:
        recipient.status = "failed"
        recipient.error = "渠道不存在"
        record_event(db, recipient, "failed", {"error": "渠道不存在"})
        return

    variables = _personalize_variables(recipient)
    html = render_body(campaign.body, campaign.mode, variables)
    subject = render_body(campaign.subject, "html", variables)
    text = make_text_version(html)

    attachments = [
        OutgoingAttachment(
            filename=a.filename,
            content=open(a.stored_path, "rb").read(),
            mime=a.mime,
            cid=a.cid,
        )
        for a in campaign.attachments
    ]

    from_addr = (channel.config or {}).get("from", "")
    msg = OutgoingMessage(
        from_addr=from_addr,
        to=recipient.email,
        subject=subject,
        html=html,
        text=text,
        headers=_unsubscribe_headers(db, recipient.email),
        attachments=attachments,
    )

    recipient.status = "sending"
    db.commit()
    try:
        mid = send_message(channel.kind, channel.config or {}, msg)
    except SendError as e:
        recipient.attempts += 1
        if recipient.attempts > campaign.max_retries:
            recipient.status = "failed"
            recipient.error = str(e)
            record_event(db, recipient, "failed", {"error": str(e), "attempt": recipient.attempts})
        else:
            backoff = timedelta(minutes=2 ** recipient.attempts)
            recipient.status = "pending"
            recipient.next_retry_at = utcnow() + backoff
            recipient.error = str(e)
            record_event(db, recipient, "retry", {"error": str(e), "attempt": recipient.attempts,
                                                  "next_retry_at": (utcnow() + backoff).isoformat()})
        return

    recipient.status = "sent"
    recipient.provider_message_id = mid
    recipient.sent_at = utcnow()
    recipient.error = ""
    record_event(db, recipient, "sent", {"provider_message_id": mid, "channel": channel.kind})
    contact = db.get(Contact, recipient.contact_id) if recipient.contact_id else None
    if contact:
        contact.last_email_at = utcnow()


def _unsubscribe_headers(db: Session, email: str) -> dict[str, str]:
    """退订头：从 app_settings 读 list_unsubscribe_url 模板（{email} 占位）。"""
    s = db.get(models.AppSetting, "list_unsubscribe_url")
    url = (s.value or {}).get("url", "") if s else ""
    if url and "{email}" in url:
        return {"List-Unsubscribe": f"<{url.format(email=email)}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    return {}


def _sync_counts(db: Session, campaign: Campaign) -> None:
    fresh: dict[str, int] = {}
    for r in campaign.recipients:
        fresh[r.status] = fresh.get(r.status, 0) + 1
    campaign.counts = fresh
    done = sum(fresh.get(s, 0) for s in ("sent", "delivered", "opened", "bounced", "complained", "failed", "skipped"))
    total = len(campaign.recipients)
    if campaign.status == "sending" and (total == 0 or done >= total):
        remaining_active = sum(fresh.get(s, 0) for s in ("pending", "sending"))
        if remaining_active == 0:
            campaign.status = "completed"
            campaign.finished_at = utcnow()


def tick(db_factory: sessionmaker) -> int:
    """调度推进一次：所有 sending 活动的到期收件人各发一个（受令牌桶与全局间隔约束）。

    返回本次实际发送数量。由 APScheduler 每 5 秒调用（单进程内锁防重入）。
    """
    if not _tick_lock.acquire(blocking=False):
        return 0
    sent_count = 0
    try:
        db: Session = db_factory()
        try:
            campaigns = (
                db.query(Campaign)
                .options(selectinload(Campaign.recipients), selectinload(Campaign.attachments))
                .filter(Campaign.status == "sending")
                .all()
            )
            for campaign in campaigns:
                bucket = _buckets.get(campaign.id)
                if bucket is None or bucket.rate != campaign.rate_per_minute / 60.0:
                    bucket = TokenBucket(campaign.rate_per_minute)
                    _buckets[campaign.id] = bucket

                now = utcnow()
                due = [
                    r
                    for r in campaign.recipients
                    if (r.status == "pending" and (r.next_retry_at is None or r.next_retry_at <= now))
                    or r.status == "sending"  # 上次中断卡住的
                ]
                due.sort(key=lambda r: (r.next_retry_at or now, r.id))
                batch = due[: max(1, campaign.batch_size)]
                for recipient in batch:
                    if not bucket.acquire(timeout=30.0):
                        break
                    _pacer.acquire()
                    _process_recipient(db, campaign, recipient)
                    sent_count += 1
                _sync_counts(db, campaign)
            db.commit()
        finally:
            db.close()
    except Exception:
        log.exception("campaign tick 异常")
    finally:
        _tick_lock.release()
    return sent_count


# ------------------------------------------------------------ webhook ----

def handle_provider_event(db: Session, message_id: str, event_type: str, detail: dict) -> bool:
    """按 provider_message_id 定位收件人并应用状态机（Resend webhook / 退信扫描共用）。"""
    if not message_id:
        return False
    recipient = (
        db.query(CampaignRecipient)
        .options(selectinload(CampaignRecipient.events))
        .filter(CampaignRecipient.provider_message_id == message_id)
        .first()
    )
    if recipient is None:
        return False
    if event_type == "sent":
        if recipient.status in ("pending", "sending") and not recipient.sent_at:
            recipient.status = "sent"
            recipient.sent_at = utcnow()
            record_event(db, recipient, "sent", detail)
        return True
    if apply_event(recipient, event_type):
        record_event(db, recipient, event_type, detail)
        sync_contact_status(db, recipient)
    return True
