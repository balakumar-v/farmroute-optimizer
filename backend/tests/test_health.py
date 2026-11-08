"""GET /health: public (no admin token), 200 when the database answers, 503 when it does not. No real database needed."""
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

import main


class _Conn:
    def execute(self, *_a, **_k):
        class R:
            def fetchone(self_inner):
                return {"?column?": 1}
        return R()


@contextlib.contextmanager
def _ok_conn():
    yield _Conn()


@contextlib.contextmanager
def _bad_conn():
    raise RuntimeError("postgresql://user:secret@host/db refused")
    yield


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "admin-secret")
    monkeypatch.delenv("ADMIN_AUTH_OFF", raising=False)
    return TestClient(main.app)          # no `with`: skip the startup init_db()


def test_health_ok_without_token(client, monkeypatch):
    monkeypatch.setattr(main, "get_conn", _ok_conn)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok" and r.json()["database"] == "ok"


def test_health_503_when_db_down_and_no_leak(client, monkeypatch):
    monkeypatch.setattr(main, "get_conn", _bad_conn)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded" and "secret" not in r.text


def test_other_routes_still_need_token(client):
    assert client.get("/farmers").status_code == 401
