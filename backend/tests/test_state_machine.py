"""状态机与活动引擎测试：事件时间线迁移、退信回写联系人、计划排除、webhook 处理。"""

from __future__ import annotations

from datetime import datetime, timezone

from app import models
from app.services import campaign_engine
from app.services.importer import parse_rows, import_contacts


def _mk_contact(db, email, status="active"):
    c = models.Contact(email=email, status=status)
    db.add(c)
    db.commit()
    return c


def _mk_campaign(db, channel_id=None, **kw):
    c = models.Campaign(name="测试活动", subject="Hi {{name}}", mode="rich",
                        body="<p>你好 {{name}}</p>", channel_id=channel_id, **kw)
    db.add(c)
    db.commit()
    return c


def test_state_machine_flow(db_session):
    r = models.CampaignRecipient(campaign_id=1, email="a@ex.com")
    assert campaign_engine.apply_event(r, "delivered") is False  # sent 之前无效
    assert campaign_engine.apply_event(r, "sent") is False
    r.status = "sent"
    assert campaign_engine.apply_event(r, "delivered")
    assert r.status == "delivered" and r.delivered_at is not None
    assert campaign_engine.apply_event(r, "opened")
    assert r.status == "opened"
    assert campaign_engine.apply_event(r, "bounced")
    assert r.status == "bounced"


def test_state_machine_idempotent(db_session):
    r = models.CampaignRecipient(campaign_id=1, email="a@ex.com", status="sent")
    assert campaign_engine.apply_event(r, "delivered")
    d1 = r.delivered_at
    assert campaign_engine.apply_event(r, "delivered") is False  # 重复事件不迁移
    assert r.delivered_at == d1


def test_plan_excludes_blocked(db_session):
    import_contacts(db_session, parse_rows("a@ex.com\nb@ex.com\nc@ex.com\n", "txt"))
    _mk_contact(db_session, "gone@ex.com", status="unsubscribed")
    c = _mk_campaign(db_session)
    tag = models.Tag(name="T1")
    db_session.add(tag)
    db_session.commit()
    for contact in db_session.query(models.Contact).all():
        contact.tags.append(tag)
    db_session.commit()

    stats = campaign_engine.set_recipients(db_session, c, tag_ids=[tag.id])
    assert stats["recipients_total"] == 3  # gone 被排除
    assert stats["excluded_blocked"] == 1

    plan = campaign_engine.build_plan(db_session, c)
    assert plan["total"] == 3
    assert plan["channel"] is None  # 未选渠道
    assert plan["batches"] >= 1


def test_cancel_marks_skipped(db_session):
    c = _mk_campaign(db_session)
    campaign_engine.set_recipients(db_session, c, contact_ids=[_mk_contact(db_session, "x@ex.com").id])
    c.status = "sending"
    campaign_engine.cancel_campaign(db_session, c)
    assert c.status == "cancelled"
    assert all(r.status == "skipped" for r in c.recipients)


def test_webhook_event_updates_recipient_and_contact(db_session):
    contact = _mk_contact(db_session, "victim@ex.com")
    ch = models.Channel(kind="resend", name="R", config={"api_key": "k", "from": "hi@ex.com"})
    db_session.add(ch)
    c = _mk_campaign(db_session, channel_id=ch.id)
    campaign_engine.set_recipients(db_session, c, contact_ids=[contact.id])
    c.status = "sending"
    r = c.recipients[0]
    r.status = "sent"
    r.provider_message_id = "re-123"
    db_session.commit()

    assert campaign_engine.handle_provider_event(db_session, "re-123", "delivered", {})
    assert campaign_engine.handle_provider_event(db_session, "re-123", "bounced", {"reason": "hard"})
    db_session.commit()
    assert r.status == "bounced"
    assert contact.status == "bounced"  # 联系人自动降级
    types = [e.type for e in r.events]
    assert types == ["delivered", "bounced"]


def test_tick_sends_and_completes(db_session, monkeypatch):
    """模拟渠道发送成功：tick 推进 pending → sent → completed。"""
    import app.services.campaign_engine as engine
    from app.services.sender import OutgoingMessage

    sent_log = []

    def fake_send(kind, config, msg: OutgoingMessage):
        sent_log.append(msg.to)
        return f"mid-{msg.to}"

    monkeypatch.setattr(engine, "send_message", fake_send)
    monkeypatch.setattr(engine, "_pacer", engine.GlobalPacer(min_interval=0.0))

    contact = _mk_contact(db_session, "tick@ex.com")
    ch = models.Channel(kind="smtp", name="S", config={"smtp": {"host": "smtp.test", "port": 587, "from": "hi@ex.com"}, "from": "hi@ex.com"})
    db_session.add(ch)
    db_session.flush()
    c = _mk_campaign(db_session, channel_id=ch.id, rate_per_minute=600)
    campaign_engine.set_recipients(db_session, c, contact_ids=[contact.id])
    campaign_engine.confirm_campaign(db_session, c)

    sent = engine.tick(lambda: db_session)
    assert sent == 1
    r = c.recipients[0]
    assert r.status == "sent" and r.provider_message_id == "mid-tick@ex.com"
    assert c.status == "completed"
    assert contact.last_email_at is not None


def test_tick_retries_with_backoff(db_session, monkeypatch):
    import app.services.campaign_engine as engine

    calls = {"n": 0}

    def fake_send(kind, config, msg):
        calls["n"] += 1
        raise engine.SendError("smtp down")

    monkeypatch.setattr(engine, "send_message", fake_send)
    monkeypatch.setattr(engine, "_pacer", engine.GlobalPacer(min_interval=0.0))

    contact = _mk_contact(db_session, "retry@ex.com")
    ch = models.Channel(kind="smtp", name="S", config={"from": "hi@ex.com"})
    db_session.add(ch)
    db_session.flush()
    c = _mk_campaign(db_session, channel_id=ch.id, rate_per_minute=600, max_retries=1)
    campaign_engine.set_recipients(db_session, c, contact_ids=[contact.id])
    campaign_engine.confirm_campaign(db_session, c)

    engine.tick(lambda: db_session)
    r = c.recipients[0]
    assert r.status == "pending" and r.attempts == 1  # 第一次失败 → 待重试
    assert r.next_retry_at is not None
    assert calls["n"] == 1

    engine.tick(lambda: db_session)  # 未到重试时间 → 不发
    assert calls["n"] == 1
