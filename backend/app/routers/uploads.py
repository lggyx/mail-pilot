"""附件/图片上传与下载。存本地 data/attachments/；图片可生成 CID 供内嵌。"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session as DBSession
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import models
from ..auth import current_user
from ..config import settings
from ..db import get_db

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

MAX_SIZE = 20 * 1024 * 1024  # 20MB


def _att_dir() -> Path:
    d = settings.data_dir / "attachments"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("")
async def upload(
    file: UploadFile = File(...),
    embed: bool = Form(False),  # 图片内嵌：生成 CID
    campaign_id: int = Form(0),
    db: DBSession = Depends(get_db),
    _: dict = Depends(current_user),
):
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(400, "文件超过 20MB 限制")
    filename = re.sub(r"[^\w.\-\u4e00-\u9fff]", "_", file.filename or "file")[:120] or "file"
    ext = Path(filename).suffix
    stored = f"{uuid.uuid4().hex[:12]}{ext}"
    path = _att_dir() / stored
    path.write_bytes(data)

    mime = file.content_type or "application/octet-stream"
    cid = None
    if embed:
        if not mime.startswith("image/"):
            raise HTTPException(400, "只有图片可以内嵌（CID）")
        cid = uuid.uuid4().hex[:12]

    att = models.Attachment(
        campaign_id=campaign_id or None,
        filename=filename,
        stored_path=str(path),
        mime=mime,
        size=len(data),
        cid=cid,
    )
    db.add(att)
    db.commit()
    return {
        "data": {
            "id": att.id, "filename": att.filename, "mime": att.mime, "size": att.size,
            "cid": cid, "embed": embed,
        }
    }


@router.get("/{attachment_id}")
def download(attachment_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    att = db.get(models.Attachment, attachment_id)
    if not att or not Path(att.stored_path).exists():
        raise HTTPException(404, "附件不存在")
    return FileResponse(att.stored_path, media_type=att.mime, filename=att.filename)
