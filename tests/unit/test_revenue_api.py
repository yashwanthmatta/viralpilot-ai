import pytest
from fastapi.testclient import TestClient
from vp_api import security
from vp_api.app import app

CSRF = {"X-VP-CSRF": "1"}


@pytest.fixture
def client():
    security._attempts.clear()
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": "test-pass"}).status_code == 200
        yield c


def test_manual_campaign_entry_is_assessed(client):
    r = client.post("/api/campaigns", headers=CSRF, json={
        "provider": "content_rewards", "external_id": "cr-1", "name": "Pod clips", "url": "https://contentrewards.com/c/1",
        "payout_model": "cpm", "rate_per_1k": 2.0, "min_payout": 1, "max_payout_per_video": 100,
        "budget_remaining": 900, "platform_fee_pct": 0.1, "platforms": ["youtube"],
        "requirements": "30-60s clips, captions", "footage_urls": ["https://cdn.example.com/a.mp4"]})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "restricted" and "no connected account" in body["status_reason"]
    assert body["evaluation"]["label"] == "estimate"
    assert client.get("/api/campaigns").json()[0]["name"] == "Pod clips"


def test_revenue_requires_evidence_and_keeps_pending_separate(client):
    assert client.post("/api/revenue", headers=CSRF, json={
        "stream": "campaign", "amount": 12.5, "status": "confirmed", "evidence": "x", "external_ref": "p1"}).status_code == 422
    r = client.post("/api/revenue", headers=CSRF, json={
        "stream": "campaign", "amount": 12.5, "status": "pending", "evidence": "Content Rewards dashboard round 14",
        "external_ref": "cr-round-14"})
    assert r.status_code == 201
    f = client.get("/api/finance").json()["overview"]
    assert f["pending"] == 12.5 and f["confirmed_all_time"] == 0 and f["first_dollar_reached"] is False
    assert client.post(f"/api/revenue/{r.json()['id']}/confirm", headers=CSRF,
                       json={"evidence": "Whop payout po_123"}).status_code == 200
    f = client.get("/api/finance").json()
    assert f["overview"]["confirmed_month"] == 12.5 and f["overview"]["pending"] == 0
    assert f["overview"]["first_dollar_reached"] is True
    assert f["milestones"]["basis"] == "assumptions" and len(f["milestones"]["rows"]) == 8
    # duplicate reference refused
    assert client.post("/api/revenue", headers=CSRF, json={
        "stream": "campaign", "amount": 1, "status": "pending", "evidence": "dup entry", "external_ref": "cr-round-14"}).status_code == 409


def test_budget_defaults_match_spec(client):
    b = client.get("/api/budget").json()
    assert b["total_limit_usd"] == 100 and b["max_videos_ceiling"] == 5 and b["per_item_limit_usd"] == 0.5


def test_clip_media_is_served_only_from_media_dir(client, tmp_path, monkeypatch):
    from vp_shared import db
    from vp_shared.config import get_settings
    from vp_shared.models import Clip, ContentItem

    media = tmp_path / "media"
    (media / "renders").mkdir(parents=True)
    good = media / "renders" / "c.mp4"
    good.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    outside = tmp_path / "secret.txt"
    outside.write_text("nope")
    monkeypatch.setenv("MEDIA_DIR", str(media))
    assert get_settings().media_dir == str(media)
    with db.session_scope() as s:
        item = ContentItem(fingerprint="m", title="t")
        s.add(item)
        s.flush()
        ok = Clip(item_id=item.id, start_s=0, end_s=1, render_path=str(good))
        bad = Clip(item_id=item.id, start_s=0, end_s=1, render_path=str(outside))
        s.add_all([ok, bad])
        s.flush()
        ok_id, bad_id = ok.id, bad.id
    r = client.get(f"/api/clips/{ok_id}/video")
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    assert client.get(f"/api/clips/{bad_id}/video").status_code == 404
    assert client.get(f"/api/clips/{ok_id}/cover").status_code == 404
    assert client.get(f"/api/clips/{ok_id}/other").status_code == 422
    security._attempts.clear()
    with TestClient(app) as anon:
        assert anon.get(f"/api/clips/{ok_id}/video").status_code == 401
