"""认证：单用户账号密码 + itsdangerous 签名 session cookie（无服务端会话表）。"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .config import settings

COOKIE_NAME = "mp_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 天


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.secret_key, salt="mail-pilot-session")


def verify_login(username: str, password: str) -> bool:
    return secrets.compare_digest(username, settings.app_username) and secrets.compare_digest(
        password, settings.app_password
    )


def create_session_cookie(response: Response, username: str) -> None:
    token = _serializer().dumps({"u": username})
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # 生产由 Caddy 强制 HTTPS；cookie 本身 Signed
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def read_session(request: Request) -> dict[str, Any] | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        return _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except BadSignature:
        return None


def current_user(request: Request) -> dict[str, Any]:
    """FastAPI 依赖：未登录抛 401。"""
    session = read_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    return session
