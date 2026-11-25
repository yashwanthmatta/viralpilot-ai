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
