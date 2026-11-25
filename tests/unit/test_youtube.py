"""YouTube adapter against a mocked Google API (httpx.MockTransport).

This proves our request shapes, token handling, duplicate protection and
error mapping. It does NOT prove a real upload works: that needs your
Google OAuth client and a real channel (see SETUP_REQUIRED.md)."""
import json
import time

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from vp_agents.worker import run_job
from vp_api import security
from vp_api.app import app
from vp_publishing import youtube
from vp_shared import crypto, db, jobs
from vp_shared.models import (
    Clip,
    ContentItem,
    IntegrationBlocker,
    Job,
    MetricSnapshot,
    Publication,
    PublicationStatus,
    SocialAccount,
)

from tests.conftest import start_autopilot


class FakeGoogle:
    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.uploaded: list[dict] = []
        self.quota = False
        self.revoked = False
        self.existing_tags: list[str] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        url = str(req.url)
        if url.startswith(youtube.TOKEN_URL):
            form = dict(x.split("=", 1) for x in req.content.decode().split("&"))
            if form["grant_type"] == "refresh_token":
                if self.revoked:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3600})
            return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600,
                                             "scope": " ".join(youtube.SCOPES)})
        if "/youtube/v3/channels" in url:
            return httpx.Response(200, json={"items": [{"id": "UC123", "snippet": {"title": "My Shorts"},
                                                        "contentDetails": {"relatedPlaylists": {"uploads": "UU123"}}}]})
        if url.startswith(youtube.UPLOAD_URL) and req.method == "POST":
            if self.quota:
                return httpx.Response(403, json={"error": {"message": "quota", "errors": [{"reason": "quotaExceeded"}]}})
            self.uploaded.append({"params": dict(req.url.params), "body": json.loads(req.content)})
            return httpx.Response(200, headers={"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=abc"})
        if "upload_id=abc" in url and req.method == "PUT":
            assert req.headers["Content-Length"] == str(len(req.read()))
            return httpx.Response(200, json={"id": "vid42"})
        if "/youtube/v3/playlistItems" in url:
            return httpx.Response(200, json={"items": [{"contentDetails": {"videoId": "old1"}}]})
        if "/youtube/v3/videos" in url and req.url.params.get("part") == "snippet":
            return httpx.Response(200, json={"items": [{"id": "old1", "snippet": {"tags": self.existing_tags}}]})
        if "/youtube/v3/videos" in url and req.url.params.get("part") == "statistics":
            return httpx.Response(200, json={"items": [{"id": "vid42", "statistics": {
                "viewCount": "1234", "likeCount": "56", "commentCount": "7"}}]})
        return httpx.Response(404, json={"error": {"message": f"unexpected {req.method} {url}"}})


@pytest.fixture
def google(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("PUBLIC_API_URL", "https://api.example.com")
    monkeypatch.setenv("CREDENTIALS_KEY", Fernet.generate_key().decode())
    fake = FakeGoogle()
    youtube.set_http(httpx.Client(transport=httpx.MockTransport(fake)))
    yield fake
    youtube.set_http(None)


def _account(s, *, expires_in=3600):
    acc = SocialAccount(platform="youtube", display_name="My Shorts", publishing_allowed=True, max_posts_per_day=3,
                        external_account_id="UC123",
                        encrypted_credentials=crypto.encrypt({"access_token": "at-1", "refresh_token": "rt-1",
                                                              "expires_at": time.time() + expires_in,
                                                              "scope": " ".join(youtube.SCOPES), "uploads": "UU123"}))
    s.add(acc)
    s.flush()
    return acc


def _pub(tmp_path, *, paid=False, expires_in=3600):
    video = tmp_path / "c.mp4"
    video.write_bytes(b"\x00" * 5000)
    start_autopilot()
    with db.session_scope() as s:
        acc = _account(s, expires_in=expires_in)
        item = ContentItem(fingerprint="y")
        s.add(item)
        s.flush()
        clip = Clip(item_id=item.id, start_s=0, end_s=30, render_path=str(video), title="Why startups fail",
                    description="Cash flow.\n\n#Shorts #startups", hashtags=["#Shorts", "#startups"],
                    features={"metadata": {"paid_promotion": paid}})
        s.add(clip)
        s.flush()
        pub = Publication(clip_id=clip.id, account_id=acc.id, platform="youtube", idempotency_key=f"clip{clip.id}-acct{acc.id}")
        s.add(pub)
        s.flush()
        jid = jobs.enqueue(s, "publish.publication", f"pub:{pub.id}", {"publication_id": pub.id}).id
        return pub.id, jid, acc.id


def test_upload_confirmed_by_video_id_and_metrics_follow(google, tmp_path):
    pid, jid, _ = _pub(tmp_path)
    assert run_job(jid) == "succeeded"
    with db.session_scope() as s:
        p = s.get(Publication, pid)
        assert p.status == PublicationStatus.published and p.platform_post_id == "vid42"
        assert p.platform_url == "https://www.youtube.com/shorts/vid42"
        body = google.uploaded[0]["body"]
        assert body["snippet"]["title"] == "Why startups fail" and body["status"]["selfDeclaredMadeForKids"] is False
        assert f"vp-clip{p.clip_id}-acct{p.account_id}" in body["snippet"]["tags"]
        assert "paidProductPlacementDetails" not in google.uploaded[0]["params"]["part"]
        metric_jobs = s.query(Job).filter_by(kind="analytics.publication").all()
        assert len(metric_jobs) == 5
        metric_jobs[0].run_after = jobs.now_utc()
        mj = metric_jobs[0].id
    assert run_job(mj) == "succeeded"
    with db.session_scope() as s:
        m = s.query(MetricSnapshot).one()
        assert (m.views, m.likes, m.comments) == (1234, 56, 7)


def test_paid_campaign_clip_declares_paid_placement(google, tmp_path):
    _, jid, _ = _pub(tmp_path, paid=True)
    assert run_job(jid) == "succeeded"
    up = google.uploaded[0]
    assert "paidProductPlacementDetails" in up["params"]["part"]
    assert up["body"]["paidProductPlacementDetails"] == {"hasPaidProductPlacement": True}


def test_expired_access_token_is_refreshed_and_stored(google, tmp_path):
    _, jid, aid = _pub(tmp_path, expires_in=-10)
    assert run_job(jid) == "succeeded"
    with db.session_scope() as s:
        assert crypto.decrypt(s.get(SocialAccount, aid).encrypted_credentials)["access_token"] == "at-2"


def test_revoked_access_pauses_account_and_blocks(google, tmp_path):
    google.revoked = True
    pid, jid, aid = _pub(tmp_path, expires_in=-10)
    assert run_job(jid) == "blocked"
    with db.session_scope() as s:
        acc = s.get(SocialAccount, aid)
        assert acc.health == "paused" and "reconnect" in acc.health_note
        assert s.query(IntegrationBlocker).filter_by(key=f"account.{aid}.connect").one()
        assert s.get(Publication, pid).status != PublicationStatus.published
    assert google.uploaded == []


def test_quota_exceeded_waits_and_does_not_fail(google, tmp_path):
    google.quota = True
    pid, jid, _ = _pub(tmp_path)
    assert run_job(jid) == "retry-later"
    with db.session_scope() as s:
        assert s.get(Publication, pid).status == PublicationStatus.publishing
        assert (jobs.as_utc(s.get(Job, jid).run_after) - jobs.now_utc()).total_seconds() > 5 * 3600


def test_interrupted_upload_is_found_by_tag_not_reuploaded(google, tmp_path):
    pid, jid, _ = _pub(tmp_path)
    with db.session_scope() as s:
        p = s.get(Publication, pid)
        p.status = PublicationStatus.publishing  # an earlier attempt crashed mid-upload
        google.existing_tags = ["startups", youtube.idempotency_tag(p)]
    assert run_job(jid) == "succeeded"
    with db.session_scope() as s:
        assert s.get(Publication, pid).platform_post_id == "old1"
    assert google.uploaded == []


def test_not_configured_is_reported_honestly(monkeypatch):
    for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "PUBLIC_API_URL"):
        monkeypatch.delenv(k, raising=False)
    st = youtube.YouTubePublisher().platform_status()
    assert not st.ok and "GOOGLE_CLIENT_ID" in st.reason


# ----------------------------------------------------------------- OAuth via the API

@pytest.fixture
def client():
    security._attempts.clear()
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": "test-pass"}).status_code == 200
        yield c


def test_oauth_connect_stores_encrypted_tokens(google, client):
    r = client.post("/api/oauth/youtube/start", headers={"X-VP-CSRF": "1"})
    assert r.status_code == 200
    url = httpx.URL(r.json()["url"])
    assert url.host == "accounts.google.com" and url.params["access_type"] == "offline"
    assert url.params["redirect_uri"] == "https://api.example.com/api/oauth/youtube/callback"
    state = url.params["state"]

    bad = client.get("/api/oauth/youtube/callback", params={"code": "c", "state": "wrong"}, follow_redirects=False)
    assert bad.status_code == 303 and "error=" in bad.headers["location"]

    client.cookies.set("vp_oauth_state", state, path="/api/oauth")
    ok = client.get("/api/oauth/youtube/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert ok.status_code == 303 and "connected=youtube" in ok.headers["location"]
    with db.session_scope() as s:
        acc = s.query(SocialAccount).filter_by(platform="youtube").one()
        assert acc.external_account_id == "UC123" and acc.display_name == "My Shorts"
        assert "rt-1" not in acc.encrypted_credentials  # encrypted at rest
        assert crypto.decrypt(acc.encrypted_credentials)["refresh_token"] == "rt-1"
        assert acc.publishing_allowed is False  # the owner still has to allow publishing
    accs = client.get("/api/accounts").json()
    assert accs[0]["connected"] and accs[0]["can_publish"]


def test_oauth_start_requires_config(client, monkeypatch):
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert client.post("/api/oauth/youtube/start", headers={"X-VP-CSRF": "1"}).status_code == 409
