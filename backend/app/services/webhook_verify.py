"""Resend webhook 验签（svix 协议：svix-id / svix-timestamp / svix-signature 头）。

签名串 = "{id}.{timestamp}.{raw_body}"，HMAC-SHA256（密钥为 whsec_ 前缀 base64）。
时间戳容差 ±5 分钟，防重放。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

TOLERANCE_SECONDS = 300


class WebhookVerificationError(Exception):
    pass


def verify_svix(secret: str, msg_id: str, timestamp: str, signature_header: str, payload: bytes) -> None:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError) as e:
        raise WebhookVerificationError("时间戳缺失或非法") from e
    if abs(time.time() - ts) > TOLERANCE_SECONDS:
        raise WebhookVerificationError("webhook 时间戳超出容差（可能重放）")

    key_b64 = secret.removeprefix("whsec_")
    try:
        key = base64.b64decode(key_b64)
    except Exception as e:
        raise WebhookVerificationError("webhook secret 格式错误") from e

    signed_content = f"{msg_id}.{timestamp}.".encode() + payload
    expected = base64.b64encode(hmac.new(key, signed_content, hashlib.sha256).digest()).decode()

    signatures = [s.strip() for s in (signature_header or "").split(",") if s.strip()]
    if not any(hmac.compare_digest(sig, expected) for sig in signatures):
        raise WebhookVerificationError("签名不匹配")
