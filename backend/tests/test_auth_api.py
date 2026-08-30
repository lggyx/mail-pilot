"""认证与 API 冒烟测试：登录/保护路由/导入 API/活动流程 API/webhook 验签。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from app.config import settings
from app.services.webhook_verify import verify_svix, WebhookVerificationError


def test_health_no_auth(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_protected_without_login(client):
    resp = client.get("/api/contacts")
    assert resp.status_code == 401


def test_login_wrong_password(client):
    resp = client.post("/api/auth/login", json={"username": settings.app_username, "password": "wrong"})
    assert resp.status_code == 401


def test_login_and_me(auth_client):
    resp = auth_client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.json()["data"]["username"] == settings.app_username


def test_logout(auth_client):
    auth_client.post("/api/auth/logout")
    assert auth_client.get("/api/auth/me").status_code == 401


def test_import_api(auth_client):
    resp = auth_client.post(
        "/api/contacts/import",
        data={"text": "a@ex.com\nName <b@ex.com>\nb@ex.com\n", "fmt": "paste", "tag_ids": "[]"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["added"] == 2
    assert data["skipped_duplicates"] == 1

    listing = auth_client.get("/api/contacts?q=a@ex").json()["data"]
    assert listing["total"] == 1


def test_tags_and_filter(auth_client):
    tag = auth_client.post("/api/tags", json={"name": "内测"}).json()["data"]
    auth_client.post("/api/contacts/import", data={"text": "t1@ex.com\nt2@ex.com\n", "fmt": "paste", "tag_ids": "[]"})
    cid = auth_client.get("/api/contacts?q=t1@ex").json()["data"]["items"][0]["id"]
    auth_client.put(f"/api/contacts/{cid}", json={"tag_ids": [tag["id"]]})
    got = auth_client.get(f"/api/contacts?tag_id={tag['id']}").json()["data"]
    assert got["total"] == 1


def test_campaign_flow_api(auth_client):
    # 渠道
    ch = auth_client.post("/api/channels", json={
        "kind": "smtp", "name": "测试 SMTP",
        "config": {"from": "hi@ex.com", "smtp": {"host": "smtp.test", "port": 587}},
        "is_default": True,
    }).json()["data"]
    # 导入联系人
    auth_client.post("/api/contacts/import", data={"text": "c1@ex.com\nc2@ex.com\n", "fmt": "paste", "tag_ids": "[]"})
    # 活动
    cp = auth_client.post("/api/campaigns", json={
        "name": "八月通知", "subject": "Hi {{name}}", "mode": "rich", "body": "<p>你好 {{name}}</p>",
        "channel_id": ch["id"],
    }).json()["data"]
    # 收件人（无标签 → 用指定 id）
    contacts = auth_client.get("/api/contacts").json()["data"]["items"]
    stats = auth_client.put(f"/api/campaigns/{cp['id']}/recipients",
                            json={"tag_ids": [], "contact_ids": [c["id"] for c in contacts]}).json()["data"]
    assert stats["recipients_total"] == 2
    plan = auth_client.post(f"/api/campaigns/{cp['id']}/plan").json()["data"]
    assert plan["total"] == 2 and plan["channel"]["id"] == ch["id"]
    assert auth_client.post(f"/api/campaigns/{cp['id']}/confirm").status_code == 200
    detail = auth_client.get(f"/api/campaigns/{cp['id']}").json()["data"]
    assert detail["status"] == "sending"
    # 暂停/继续
    auth_client.post(f"/api/campaigns/{cp['id']}/pause")
    assert auth_client.get(f"/api/campaigns/{cp['id']}").json()["data"]["status"] == "paused"
    auth_client.post(f"/api/campaigns/{cp['id']}/resume")
    # 取消 → skipped
    auth_client.post(f"/api/campaigns/{cp['id']}/cancel")
    recs = auth_client.get(f"/api/campaigns/{cp['id']}/recipients").json()["data"]
    assert all(r["status"] == "skipped" for r in recs["items"])
    # 时间线
    rid = recs["items"][0]["id"]
    events = auth_client.get(f"/api/campaigns/{cp['id']}/recipients/{rid}/events").json()["data"]
    assert any(e["type"] == "skipped" for e in events["events"])


def _svix_signature(secret: str, msg_id: str, ts: str, payload: bytes) -> str:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signed = f"{msg_id}.{ts}.".encode() + payload
    return base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()


def test_svix_verify_roundtrip():
    secret = "whsec_" + base64.b64encode(b"x" * 24).decode()
    ts = str(int(time.time()))
    payload = b'{"type":"email.delivered"}'
    sig = _svix_signature(secret, "msg_1", ts, payload)
    verify_svix(secret, "msg_1", ts, sig, payload)  # 不抛即通过
    try:
        verify_svix(secret, "msg_1", ts, "badsig", payload)
        assert False, "应当验签失败"
    except WebhookVerificationError:
        pass


def test_resend_webhook_without_secret(auth_client):
    """未配置 webhook_secret 时（开发模式）放行并处理事件。"""
    ch = auth_client.post("/api/channels", json={"kind": "resend", "name": "R", "config": {"api_key": "k", "from": "hi@ex.com"}}).json()["data"]
    auth_client.post("/api/contacts/import", data={"text": "w@ex.com\n", "fmt": "paste", "tag_ids": "[]"})
    cid = auth_client.get("/api/contacts").json()["data"]["items"][0]["id"]
    cp = auth_client.post("/api/campaigns", json={"name": "W", "channel_id": ch["id"], "subject": "s", "body": "b"}).json()["data"]
    auth_client.put(f"/api/campaigns/{cp['id']}/recipients", json={"tag_ids": [], "contact_ids": [cid]})
    payload = {"type": "email.delivered", "data": {"email_id": "re-xyz"}}
    r = auth_client.post("/api/webhooks/resend", json=payload)
    assert r.status_code == 200
