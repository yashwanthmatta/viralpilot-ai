"""Publishing safety rules. These use a fake adapter: they prove our own
logic, NOT that any real platform integration works."""
import pytest
import vp_publishing
from vp_agents.worker import run_job
from vp_shared import db, jobs
from vp_shared.models import Clip, ContentItem, IntegrationBlocker, Job, Publication, PublicationStatus, SocialAccount

from tests.conftest import start_autopilot


class FakeAdapter(vp_publishing.Publisher):
    platform = "fakeplat"

    def __init__(self, post_id="p-1", lookup_result=NotImplemented, explode=False):
        self.calls, self.post_id, self.lookup_result, self.explode = 0, post_id, lookup_result, explode

    def availability(self, account):
        return vp_publishing.Availability(True)

    def publish(self, account, clip, pub):
        self.calls += 1
        if self.explode:
            raise ConnectionError("network dropped after upload")
        return vp_publishing.Confirmation(self.post_id, f"https://fake/{self.post_id}")

    def lookup(self, account, pub):
        return self.lookup_result


@pytest.fixture
def adapter(monkeypatch):
    a = FakeAdapter()
    monkeypatch.setitem(vp_publishing.REGISTRY, "fakeplat", a)
    return a


def _setup(platform="fakeplat", allowed=True, max_per_day=2, n=1):
    start_autopilot()
    ids = []
    with db.session_scope() as s:
        acc = SocialAccount(platform=platform, display_name="me", publishing_allowed=allowed,
                            max_posts_per_day=max_per_day)
        item = ContentItem(fingerprint="f")
        s.add_all([acc, item])
        s.flush()
        for i in range(n):
            clip = Clip(item_id=item.id, start_s=0, end_s=30)
            s.add(clip)
            s.flush()
            pub = Publication(clip_id=clip.id, account_id=acc.id, platform=platform,
                              idempotency_key=f"{clip.id}:{acc.id}")
            s.add(pub)
            s.flush()
            jid = jobs.enqueue(s, "publish.publication", f"pub:{pub.id}", {"publication_id": pub.id}).id
            ids.append((pub.id, jid))
    return ids


def _pub(pid):
    with db.session_scope() as s:
        return s.get(Publication, pid)


def test_published_only_with_platform_id(adapter):
    [(pid, jid)] = _setup()
    assert run_job(jid) == "succeeded"
    p = _pub(pid)
    assert p.status == PublicationStatus.published and p.platform_post_id == "p-1"


def test_empty_post_id_is_not_published(adapter):
    adapter.post_id = ""
    [(pid, jid)] = _setup()
    run_job(jid)
    assert _pub(pid).status == PublicationStatus.failed


def test_rerun_does_not_republish(adapter):
    [(pid, jid)] = _setup()
    run_job(jid)
    with db.session_scope() as s:
        s.get(Job, jid).status = jobs.JobStatus.pending
    run_job(jid)
    assert adapter.calls == 1


def test_interrupted_publish_never_double_posts(adapter):
    adapter.explode = True
    [(pid, jid)] = _setup()
    assert run_job(jid) == "retrying"
    assert _pub(pid).status == PublicationStatus.publishing  # unknown outcome is remembered
    adapter.explode = False
    with db.session_scope() as s:
        s.get(Job, jid).run_after = jobs.now_utc()
    run_job(jid)
    assert adapter.calls == 1  # no second upload without a way to check
    assert _pub(pid).status == PublicationStatus.failed
    with db.session_scope() as s:
        assert s.query(IntegrationBlocker).filter(IntegrationBlocker.key.like("pub.unknown.%")).count() == 1


def test_interrupted_publish_recovered_by_lookup(adapter):
    adapter.explode = True
    [(pid, jid)] = _setup()
    run_job(jid)
    adapter.explode = False
    adapter.lookup_result = vp_publishing.Confirmation("found-9")
    with db.session_scope() as s:
        s.get(Job, jid).run_after = jobs.now_utc()
    run_job(jid)
    assert adapter.calls == 1
    assert _pub(pid).platform_post_id == "found-9"


def test_permission_switch_respected(adapter):
    [(pid, jid)] = _setup(allowed=False)
    run_job(jid)
    assert _pub(pid).status == PublicationStatus.blocked and adapter.calls == 0


def test_unapproved_platform_is_blocked_not_attempted():
    [(pid, jid)] = _setup(platform="tiktok")
    assert run_job(jid) == "blocked"
    p = _pub(pid)
    assert p.status == PublicationStatus.scheduled and "audit" in p.error  # keeps its place, re-checks later
    with db.session_scope() as s:
        assert s.query(IntegrationBlocker).filter_by(key="platform.tiktok").one()


def test_daily_cap(adapter):
    ids = _setup(max_per_day=1, n=2)
    assert run_job(ids[0][1]) == "succeeded"
    assert run_job(ids[1][1]) == "retry-later"
    assert adapter.calls == 1
