from datetime import timedelta

from vp_shared import db, jobs
from vp_shared.models import Job, JobStatus


def test_enqueue_is_idempotent(s):
    assert jobs.enqueue(s, "k", "same") is not None
    assert jobs.enqueue(s, "k", "same") is None
    assert s.query(Job).count() == 1


def test_claim_is_exclusive():
    with db.session_scope() as s:
        jid = jobs.enqueue(s, "k", "a").id
    with db.session_scope() as s:
        assert jobs.claim(s, jid) is not None
    with db.session_scope() as s:
        assert jobs.claim(s, jid) is None


def test_expired_lease_is_recovered():
    with db.session_scope() as s:
        jid = jobs.enqueue(s, "k", "a").id
    with db.session_scope() as s:
        jobs.claim(s, jid)
    later = jobs.now_utc() + timedelta(hours=2)
    with db.session_scope() as s:
        assert jobs.recover_expired(s, later) == 1
        j = s.get(Job, jid)
        assert j.status == JobStatus.pending and "lease expired" in j.last_error


def test_backoff_then_dead_letter(s):
    j = jobs.enqueue(s, "k", "a", max_attempts=2)
    j.attempts = 1
    jobs.fail(s, j, "boom")
    assert j.status == JobStatus.pending and jobs.as_utc(j.run_after) > jobs.now_utc()
    j.attempts = 2
    jobs.fail(s, j, "boom again")
    assert j.status == JobStatus.failed
