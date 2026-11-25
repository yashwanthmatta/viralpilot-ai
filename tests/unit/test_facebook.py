"""Facebook Reels adapter against a mocked Graph API. Proves request shapes,
step-by-step crash safety and confirmation rules; NOT a real post."""
import json

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from vp_agents.worker import run_job
from vp_api import security
from vp_api.app import app
from vp_publishing import facebook
from vp_shared import crypto, db, jobs
from vp_shared.models import Clip, ContentItem, Job, MetricSnapshot, Publication, PublicationStatus, SocialAccount

from tests.conftest import start_autopilot


class FakeGraph:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.publish_status = "published"
        self.fail_upload = False
        self.starts = 0
        self.finishes = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        self.calls.append((req.method, url.split("?")[0]))
        if "/oauth/access_token" in url:
            return httpx.Response(200, json={"access_token": "long-user" if "fb_exchange_token" in url else "short"})
        if url.split("?")[0].endswith("/me/accounts"):
            return httpx.Response(200, json={"data": [
                {"id": "PAGE1", "name": "My Page", "access_token": "page-tok", "tasks": ["CREATE_CONTENT", "ANALYZE"]},
                {"id": "PAGE2", "name": "Read only", "access_token": "x", "tasks": ["ANALYZE"]}]})
        if url.endswith("/PAGE1/video_reels") and req.method == "POST":
            body = json.loads(req.content)
            if body["upload_phase"] == "start":
                self.starts += 1
                return httpx.Response(200, json={"video_id": "V9", "upload_url": "https://rupload.facebook.com/video-upload/V9"})
            self.finishes += 1
            assert body["video_state"] == "PUBLISHED" and body["video_id"] == "V9"
            return httpx.Response(200, json={"success": True})
        if url.startswith(facebook.RUPLOAD) and req.method == "POST":
            assert req.headers["Authorization"] == "OAuth page-tok" and req.headers["offset"] == "0"
            if self.fail_upload:
                raise httpx.ConnectError("connection reset")
            return httpx.Response(200, json={"success": True})
        if "/V9/video_insights" in url:
            return httpx.Response(200, json={"data": [
                {"name": "blue_reels_play_count", "values": [{"value": 321}]},
                {"name": "post_video_social_actions", "values": [{"value": {"COMMENT": 4, "SHARE": 2}}]}]})
        if url.split("?")[0].endswith("/V9"):
            return httpx.Response(200, json={"status": {"video_status": "ready",
                                                        "publishing_phase": {"publish_status": self.publish_status}}})
        return httpx.Response(404, json={"error": {"message": f"unexpected {url}", "code": 100}})


@pytest.fixture
def graph(monkeypatch):
    monkeypatch.setenv("META_APP_ID", "123")
    monkeypatch.setenv("META_APP_SECRET", "test-app-secret")
    monkeypatch.setenv("PUBLIC_API_URL", "https://api.example.com")
    monkeypatch.setenv("CREDENTIALS_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(facebook, "CONFIRM_WAIT_S", 0)
    fake = FakeGraph()
    facebook.set_http(httpx.Client(transport=httpx.MockTransport(fake)))
    yield fake
    facebook.set_http(None)


def _pub(tmp_path):
    video = tmp_path / "r.mp4"
    video.write_bytes(b"\x00" * 3000)
    start_autopilot()
    with db.session_scope() as s:
        acc = SocialAccount(platform="facebook", display_name="My Page", external_account_id="PAGE1",
                            publishing_allowed=True, max_posts_per_day=3,
                            encrypted_credentials=crypto.encrypt({"page_token": "page-tok"}))
        item = ContentItem(fingerprint="fb")
        s.add_all([acc, item])
        s.flush()
        clip = Clip(item_id=item.id, start_s=0, end_s=30, render_path=str(video), title="T", description="D #ad")
        s.add(clip)
        s.flush()
        pub = Publication(clip_id=clip.id, account_id=acc.id, platform="facebook", idempotency_key=f"c{clip.id}")
        s.add(pub)
        s.flush()
        return pub.id, jobs.enqueue(s, "publish.publication", f"pub:{pub.id}", {"publication_id": pub.id}).id


def _due(jid):
    with db.session_scope() as s:
        s.get(Job, jid).run_after = jobs.now_utc()


def test_reel_confirmed_only_when_facebook_says_published(graph, tmp_path):
    pid, jid = _pub(tmp_path)
    assert run_job(jid) == "succeeded"
    with db.session_scope() as s:
        p = s.get(Publication, pid)
        assert p.status == PublicationStatus.published and p.platform_post_id == "V9"
        assert p.platform_url == "https://www.facebook.com/reel/V9"
        mj = s.query(Job).filter_by(kind="analytics.publication").order_by(Job.id).first()
        mj.run_after = jobs.now_utc()
        mid = mj.id
    assert run_job(mid) == "succeeded"
    with db.session_scope() as s:
        m = s.query(MetricSnapshot).one()
        assert (m.views, m.comments, m.shares) == (321, 4, 2)


def test_still_processing_is_not_reported_published_and_no_second_post(graph, tmp_path):
    graph.publish_status = "scheduled"
    pid, jid = _pub(tmp_path)
    assert run_job(jid) == "retry-later"
    assert _status(pid) == PublicationStatus.publishing
    graph.publish_status = "published"
    _due(jid)
    assert run_job(jid) == "succeeded"
    assert _status(pid) == PublicationStatus.published
    assert graph.starts == 1 and graph.finishes == 1


def test_crash_during_upload_restarts_upload_without_finishing_twice(graph, tmp_path):
    graph.fail_upload = True
    pid, jid = _pub(tmp_path)
    assert run_job(jid) == "retrying"
    with db.session_scope() as s:
        assert s.get(Publication, pid).platform_state == {"video_id": "V9", "step": "started"}
    graph.fail_upload = False
    _due(jid)
    assert run_job(jid) == "succeeded"
    assert graph.finishes == 1 and _status(pid) == PublicationStatus.published


def _status(pid):
    with db.session_scope() as s:
        return s.get(Publication, pid).status


@pytest.fixture
def client():
    security._attempts.clear()
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": "test-pass"}).status_code == 200
        yield c


def test_connect_adds_only_pages_where_user_can_post(graph, client):
    r = client.post("/api/oauth/facebook/start", headers={"X-VP-CSRF": "1"})
    url = httpx.URL(r.json()["url"])
    assert url.host == "www.facebook.com" and "pages_manage_posts" in url.params["scope"]
    state = url.params["state"]
    client.cookies.set("vp_oauth_state", state, path="/api/oauth")
    ok = client.get("/api/oauth/facebook/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert ok.status_code == 303 and "connected=facebook" in ok.headers["location"]
    with db.session_scope() as s:
        accs = s.query(SocialAccount).filter_by(platform="facebook").all()
        assert [a.external_account_id for a in accs] == ["PAGE1"]
        assert crypto.decrypt(accs[0].encrypted_credentials)["page_token"] == "page-tok"
        assert accs[0].publishing_allowed is False
