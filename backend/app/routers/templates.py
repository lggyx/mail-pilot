"""模板 CRUD 路由（变量自动提取）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session as DBSession
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import models
from ..auth import current_user
from ..db import get_db
from ..services.renderer import extract_variables

router = APIRouter(prefix="/api/templates", tags=["templates"])


class TemplateIn(BaseModel):
    name: str
    subject: str = ""
    mode: str = "rich"
    body: str = ""


def _dto(t: models.Template) -> dict:
    return {
        "id": t.id, "name": t.name, "subject": t.subject, "mode": t.mode, "body": t.body,
        "variables": t.variables or [],
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.get("")
def list_templates(db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    rows = db.query(models.Template).order_by(models.Template.updated_at.desc()).all()
    return {"data": [_dto(t) for t in rows]}


@router.post("")
def create_template(body: TemplateIn, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    if not body.name.strip():
        raise HTTPException(400, "模板名不能为空")
    if body.mode not in ("rich", "markdown", "html"):
        raise HTTPException(400, "mode 必须是 rich/markdown/html")
    t = models.Template(name=body.name.strip(), subject=body.subject, mode=body.mode,
                        body=body.body, variables=extract_variables(body.body + " " + body.subject))
    db.add(t)
    db.commit()
    return {"data": _dto(t)}


@router.put("/{template_id}")
def update_template(template_id: int, body: TemplateIn, db: DBSession = Depends(get_db),
                    _: dict = Depends(current_user)):
    t = db.get(models.Template, template_id)
    if not t:
        raise HTTPException(404, "模板不存在")
    t.name = body.name.strip() or t.name
    t.subject = body.subject
    t.mode = body.mode if body.mode in ("rich", "markdown", "html") else t.mode
    t.body = body.body
    t.variables = extract_variables(body.body + " " + body.subject)
    t.updated_at = datetime.utcnow()
    db.commit()
    return {"data": _dto(t)}


@router.get("/{template_id}")
def get_template(template_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    t = db.get(models.Template, template_id)
    if not t:
        raise HTTPException(404, "模板不存在")
    return {"data": _dto(t)}


@router.delete("/{template_id}")
def delete_template(template_id: int, db: DBSession = Depends(get_db), _: dict = Depends(current_user)):
    t = db.get(models.Template, template_id)
    if t:
        db.delete(t)
        db.commit()
    return {"data": {"ok": True}}
