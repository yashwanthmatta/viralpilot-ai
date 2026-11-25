"""Runs the real stack locally: PostgreSQL + Redis + a Celery worker process
+ a local HTTP server acting as an authorised RSS feed.

It proves the plumbing (beat-less supervisor tick -> Redis -> Celery ->
Postgres state) and crash recovery. It is NOT the zero-touch acceptance test:
there is no real social platform and no real licensed source involved.

Skipped unless INTEGRATION_DATABASE_URL and INTEGRATION_REDIS_URL are set.
"""
from __future__ import annotations

import http.server
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

DB_URL = os.environ.get("INTEGRATION_DATABASE_URL")
REDIS_URL = os.environ.get("INTEGRATION_REDIS_URL")
pytestmark = pytest.mark.skipif(not (DB_URL and REDIS_URL), reason="integration services not configured")


def _feed(port: int) -> bytes:
    return f"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><guid>owned-1</guid><title>My own episode</title>
<enclosure url="http://127.0.0.1:{port}/ep1.mp4" type="video/mp4" length="9"/></item>
</channel></rss>""".encode()


@pytest.fixture
def feed_server():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = _feed(self.server.server_port) if self.path == "/rss" else b"fakevideo"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_port
    srv.shutdown()


@pytest.fixture
def env(monkeypatch, tmp_path, fresh_db):
    from vp_agents import dispatch
    from vp_shared import db

    for k, v in {"DATABASE_URL": DB_URL, "REDIS_URL": REDIS_URL, "ALLOW_PRIVATE_NETWORK": "1",
                 "MEDIA_DIR": str(tmp_path / "media"), "SUPERVISOR_INTERVAL_S": "3600"}.items():
        monkeypatch.setenv(k, v)
    dispatch.set_dispatcher(None)
    dispatch._celery = None
    db.init_engine()
    db.Base.metadata.drop_all(db.engine())
    db.create_all()
    import redis

    redis.Redis.from_url(REDIS_URL).flushdb()
    yield os.environ.copy()


def _worker(env):
    return subprocess.Popen(
        [sys.executable, "-m", "celery", "-A", "vp_worker.celery_app", "worker", "--loglevel=WARNING",
         "--concurrency=1", "--pool=solo"], env=env)


def _wait(pred, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.5)
    return False


def test_real_queue_imports_and_hands_off_to_transcription(env, feed_server):
    from vp_agents import supervisor
    from vp_shared import db
    from vp_shared.events import set_autopilot
    from vp_shared.models import ContentItem, ItemStage, Job, LicenseType, Source, SourceKind

    with db.session_scope() as s:
        s.add(Source(name="local", kind=SourceKind.rss, url=f"http://127.0.0.1:{feed_server}/rss",
                     license_type=LicenseType.user_owned, rights_evidence="test fixture I own"))
        set_autopilot(s, True, "integration test")

    w = _worker(env)
    try:
        def stage_is(stage):
            with db.session_scope() as s:
                return s.query(ContentItem).filter_by(stage=stage).count() == 1

        def tick_until(pred):
            return _wait(lambda: (supervisor.tick(), pred())[1], 45)

        assert tick_until(lambda: stage_is(ItemStage.imported)), "item was not imported via Celery"

        def transcription_queued():
            with db.session_scope() as s:
                return s.query(Job).filter_by(kind="transcribe.item").count() == 1

        assert tick_until(transcription_queued)
    finally:
        w.send_signal(signal.SIGTERM)
        w.wait(20)


def test_stopped_autopilot_runs_nothing(env, feed_server):
    from vp_agents import supervisor
    from vp_shared import db, jobs
    from vp_shared.models import Job, JobStatus

    with db.session_scope() as s:
        jid = jobs.enqueue(s, "discover.source", "manual", {"source_id": 999}).id
    w = _worker(env)
    try:
        supervisor.tick()  # autopilot off: nothing is dispatched
        time.sleep(3)
        with db.session_scope() as s:
            assert s.get(Job, jid).status == JobStatus.pending
    finally:
        w.send_signal(signal.SIGTERM)
        w.wait(20)
