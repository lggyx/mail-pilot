"""FastAPI 应用装配：路由、静态托管、APScheduler、启动初始化。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import SessionLocal, init_db
from . import models
from .routers import (
    ai,
    auth,
    campaigns,
    channels,
    contacts,
    inbox,
    settings as settings_router,
    templates,
    uploads,
    webhooks,
)

logging.basicConfig(level=settings.log_level.upper())
log = logging.getLogger("mail-pilot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = None
    if settings.run_scheduler:
        scheduler = _start_scheduler()
        log.info("APScheduler 已启动（发送推进 / IMAP 同步 / 退信扫描）")
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


def _start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    from .services import imap_sync
    from .services.campaign_engine import tick

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        lambda: tick(SessionLocal), "interval", seconds=5, id="campaign_tick", max_instances=1,
    )

    def _imap_job():
        """IMAP 同步 + 退信扫描（有配置 IMAP 的渠道才执行；默认 30 分钟）。"""
        db = SessionLocal()
        try:
            for ch in db.query(models.Channel).filter(models.Channel.kind == "smtp").all():
                if not (ch.config or {}).get("imap", {}).get("host"):
                    continue
                try:
                    imap_sync.sync_inbox(db, ch)
                    imap_sync.scan_bounces(db, ch)
                except Exception:
                    log.exception("IMAP 同步失败：%s", ch.name)
        finally:
            db.close()

    scheduler.add_job(_imap_job, "interval", minutes=30, id="imap_sync", max_instances=1)
    scheduler.start()
    return scheduler


app = FastAPI(title="mail-pilot", version="0.1.0", lifespan=lifespan)

for r in (
    auth.router,
    contacts.router,
    templates.router,
    channels.router,
    campaigns.router,
    webhooks.router,
    uploads.router,
    ai.router,
    inbox.router,
    settings_router.router,
):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ------------------------------------------------------- 前端静态托管 ----

_static_dir = Path(settings.static_dir).resolve() if settings.static_dir else None

if _static_dir and (_static_dir / "index.html").exists():
    assets = _static_dir / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        """SPA fallback：非 /api 路径全部回 index.html；直接命中的静态文件优先。"""
        if full_path.startswith("api/"):
            return JSONResponse({"error": {"code": "not_found", "message": "接口不存在"}}, status_code=404)
        candidate = _static_dir / full_path  # type: ignore[operator]
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_static_dir / "index.html")  # type: ignore[operator]
