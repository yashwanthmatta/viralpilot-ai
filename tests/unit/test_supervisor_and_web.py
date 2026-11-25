import pytest
from fastapi.testclient import TestClient
from vp_agents import supervisor
from vp_api import security
from vp_api.app import app
from vp_shared import db
from vp_shared.models import AuditLog, IntegrationBlocker, Job, LicenseType, Source, SourceKind

from tests.conftest import start_autopilot

CSRF = {"X-VP-CSRF": "1"}


def _add_source():
    with db.session_scope() as s:
        s.add(Source(name="feed", kind=SourceKind.rss, url="https://f/rss",
                     license_type=LicenseType.user_owned, rights_evidence="mine"))


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    security._attempts.clear()


@pytest.fixture
def client():
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": "test-pass"}).status_code == 200
        yield c


def test_tick_does_nothing_while_stopped(fresh_db):
    _add_source()
    r = supervisor.tick()
    assert r["discovery_jobs"] == 0 and r["dispatched"] == 0 and fresh_db == []


def test_tick_schedules_and_dispatches_when_running(fresh_db):
    _add_source()
    start_autopilot()
    r = supervisor.tick()
    assert r["discovery_jobs"] == 1 and len(fresh_db) == 1
    assert supervisor.tick()["discovery_jobs"] == 0  # same interval: no duplicate
    with db.session_scope() as s:
        assert s.query(Job).filter_by(kind="discover.source").count() == 1


def test_tick_reports_missing_setup():
    supervisor.tick()
    with db.session_scope() as s:
        keys = {b.key for b in s.query(IntegrationBlocker).filter_by(resolved=False)}
    assert {"sources.none", "accounts.none"} <= keys


def test_auth_required_and_wrong_password():
    with TestClient(app) as c:
        assert c.get("/api/status").status_code == 401
        assert c.post("/api/auth/login", json={"password": "nope"}).status_code == 401
        assert c.get("/healthz").status_code == 200
    with db.session_scope() as s:
        assert s.query(AuditLog).filter_by(action="login_failed").count() == 1


def test_login_rate_limited():
    with TestClient(app) as c:
        codes = [c.post("/api/auth/login", json={"password": "nope"}).status_code for _ in range(6)]
    assert codes[-1] == 429


def test_tampered_cookie_rejected():
    with TestClient(app) as c:
        c.cookies.set(security.COOKIE, "admin.forged.sig")
        assert c.get("/api/status").status_code == 401


def test_csrf_header_required(client):
    assert client.post("/api/autopilot/stop").status_code == 403
    assert client.post("/api/autopilot/stop", headers=CSRF).status_code == 200


def test_start_requires_source_then_start_stop(client):
    assert client.post("/api/autopilot/start", headers=CSRF).status_code == 400
    r = client.post("/api/sources", headers=CSRF, json={
        "name": "Mine", "url": "https://feed.example/rss", "license_type": "user_owned",
        "rights_evidence": "I made it"})
    assert r.status_code == 201
    assert client.post("/api/autopilot/start", headers=CSRF).status_code == 200
    st = client.get("/api/status").json()
    assert st["autopilot"]["enabled"] is True and st["revenue"] is None
    client.post("/api/autopilot/stop", headers=CSRF)
    assert client.get("/api/status").json()["autopilot"]["enabled"] is False


def test_source_validation(client):
    r = client.post("/api/sources", headers=CSRF, json={
        "name": "x", "url": "https://f/rss", "license_type": "cc_by", "rights_evidence": "https://cc"})
    assert r.status_code == 400 and "attribution" in r.text
    r = client.post("/api/sources", headers=CSRF, json={
        "name": "x", "url": "http://f/rss", "license_type": "user_owned", "rights_evidence": "mine"})
    assert r.status_code == 422
    r = client.post("/api/sources", headers=CSRF, json={
        "name": "x", "url": "https://f/rss", "license_type": "unknown", "rights_evidence": "mine"})
    assert r.status_code == 400


def test_budget_defaults_and_update(client):
    b = client.get("/api/budget").json()
    assert b["max_videos_per_day"] == 3
    r = client.put("/api/budget", headers=CSRF, json={"daily_limit_usd": 5, "monthly_limit_usd": 100,
                                                       "per_item_limit_usd": 1, "max_videos_per_day": 3})
    assert r.status_code == 200
    assert client.put("/api/budget", headers=CSRF, json={"daily_limit_usd": -1, "monthly_limit_usd": 1,
                                                          "per_item_limit_usd": 1, "max_videos_per_day": 3}).status_code == 422


def test_platforms_report_blockers_honestly(client):
    rows = {p["platform"]: p for p in client.get("/api/platforms").json()}
    assert set(rows) == {"youtube", "tiktok", "instagram", "facebook"}
    assert rows["tiktok"]["available"] is False and "audit" in rows["tiktok"]["reason"]
