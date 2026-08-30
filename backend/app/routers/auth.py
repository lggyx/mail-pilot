"""认证路由：登录/登出/当前用户。"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from ..auth import clear_session_cookie, create_session_cookie, current_user, read_session, verify_login

router = APIRouter(prefix="/api/auth", tags=["auth"])
_login_attempts: dict[str, list[float]] = {}  # 简单防爆破：IP → 最近尝试时间


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    recent = [t for t in _login_attempts.get(ip, []) if now - t < 300]
    if len(recent) >= 10:
        raise HTTPException(429, "尝试过于频繁，请 5 分钟后再试")
    if not verify_login(body.username, body.password):
        _login_attempts.setdefault(ip, []).append(now)
        raise HTTPException(401, "用户名或密码错误")
    _login_attempts.pop(ip, None)
    create_session_cookie(response, body.username)
    return {"data": {"username": body.username}}


@router.post("/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"data": {"ok": True}}


@router.get("/me")
def me(request: Request):
    session = read_session(request)
    if not session:
        raise HTTPException(401, "未登录")
    return {"data": {"username": session.get("u", "")}}
