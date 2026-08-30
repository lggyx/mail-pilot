"""pytest 公共夹具：临时 SQLite、登录会话、禁用调度器。"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

# 让 tests 能 import app 包
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

os.environ.setdefault("RUN_SCHEDULER", "false")
os.environ.setdefault("APP_USERNAME", "testadmin")
os.environ.setdefault("APP_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret")

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import Base, get_db, make_engine, sessionmaker  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def db_engine(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    maker = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)
    db = maker()
    yield db
    db.close()


@pytest.fixture()
def client(db_engine):
    maker = sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = maker()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_client(client):
    resp = client.post("/api/auth/login", json={"username": settings.app_username,
                                                "password": settings.app_password})
    assert resp.status_code == 200, resp.text
    return client


@pytest.fixture()
def make_channel(db_session):
    def _make(kind: str = "resend", **config) -> "models.Channel":
        from app import models

        ch = models.Channel(kind=kind, name=f"测试{kind}渠道", config=config or {"api_key": "re_test", "from": "hi@example.com"})
        db_session.add(ch)
        db_session.commit()
        return ch

    return _make
