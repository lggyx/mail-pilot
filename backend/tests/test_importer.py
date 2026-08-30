"""名单导入测试：多格式解析、去重、校验、退订差集、标签。"""

from __future__ import annotations

from app import models
from app.services.importer import import_contacts, parse_rows


def _rows_csv(text: str):
    return parse_rows(text, "csv")


def test_txt_parse_keeps_duplicates_for_importer():
    rows = parse_rows("a@ex.com\nName B <b@ex.com>\nb@ex.com\n垃圾行\n", "txt")
    emails = [r.email for r in rows]
    assert emails.count("b@ex.com") == 2  # 去重交给导入层统计
    assert ("a@ex.com", "") in [(r.email, r.name) for r in rows]
    b = next(r for r in rows if r.email == "b@ex.com" and r.name)
    assert b.name == "Name B"


def test_csv_with_header():
    rows = _rows_csv("邮箱,姓名\na@ex.com,张三\nbad-email,李四\n")
    assert len(rows) == 2
    assert rows[0].email == "a@ex.com" and rows[0].name == "张三"
    assert not rows[1].valid


def test_json_formats():
    rows = parse_rows('[{"email": "A@ex.com", "name": "甲"}, "b@ex.com"]', "json")
    assert rows[0].email == "a@ex.com"  # 规范化为小写
    assert rows[1].email == "b@ex.com"


def test_xlsx_parse():
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["email", "name"])
    ws.append(["x@ex.com", "小明"])
    ws.append(["not-an-email", "小红"])
    buf = BytesIO()
    wb.save(buf)
    rows = parse_rows(buf.getvalue(), "xlsx")
    assert rows[0].email == "x@ex.com" and rows[0].name == "小明"
    assert not rows[1].valid


def test_import_dedupe_and_update(db_session):
    r1 = import_contacts(db_session, parse_rows("a@ex.com,老王\n", "txt"))
    assert r1.added == 1
    # 再导：同一邮箱不同名字 → updated（名字非空不覆盖）
    r2 = import_contacts(db_session, parse_rows("a@ex.com,新名字\n", "txt"))
    assert r2.added == 0 and r2.updated == 1
    contact = db_session.query(models.Contact).filter_by(email="a@ex.com").first()
    assert contact.name == "老王"


def test_import_excludes_unsubscribed(db_session):
    db_session.add(models.Contact(email="gone@ex.com", status="unsubscribed"))
    db_session.commit()
    report = import_contacts(db_session, parse_rows("gone@ex.com\nfresh@ex.com\n", "txt"))
    assert report.excluded_unsubscribed == 1
    assert report.added == 1


def test_import_invalid_collected(db_session):
    report = import_contacts(db_session, parse_rows("bad@@ex.com\nok@ex.com\n", "txt"))
    assert report.added == 1
    assert len(report.invalid) == 1


def test_import_tags_applied(db_session):
    tag = models.Tag(name="VIP")
    db_session.add(tag)
    db_session.commit()
    import_contacts(db_session, parse_rows("tagged@ex.com\n", "txt"), tag_ids=[tag.id])
    contact = db_session.query(models.Contact).filter_by(email="tagged@ex.com").first()
    assert [t.name for t in contact.tags] == ["VIP"]
