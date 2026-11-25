from vp_agents.stages import REGISTRY, load_all
from vp_agents.worker import run_job
from vp_shared import budget, db, jobs
from vp_shared.models import IntegrationBlocker, Job, JobStatus

from tests.conftest import start_autopilot


def _job(kind, key="k1"):
    with db.session_scope() as s:
        return jobs.enqueue(s, kind, key).id


def test_paused_when_autopilot_off():
    load_all()
    REGISTRY["test.noop"] = lambda s, j: None
    jid = _job("test.noop")
    assert run_job(jid) == "paused"
    with db.session_scope() as s:
        j = s.get(Job, jid)
        assert j.status == JobStatus.pending and j.attempts == 0


def test_success():
    load_all()
    REGISTRY["test.noop"] = lambda s, j: None
    start_autopilot()
    jid = _job("test.noop")
    assert run_job(jid) == "succeeded"


def test_unbuilt_stage_blocks_and_reports():
    start_autopilot()
    jid = _job("qc.clip")
    assert run_job(jid) == "blocked"
    with db.session_scope() as s:
        assert s.get(Job, jid).status == JobStatus.blocked
        assert s.query(IntegrationBlocker).filter_by(key="stage.qc.clip").one()


def test_budget_exhaustion_waits_without_spending():
    load_all()

    def expensive(s, j):
        budget.reserve(s, category="llm", estimate_usd=50.0)
        raise AssertionError("must not get here")

    REGISTRY["test.expensive"] = expensive
    start_autopilot()
    jid = _job("test.expensive")
    assert run_job(jid) == "budget-wait"
    with db.session_scope() as s:
        j = s.get(Job, jid)
        assert j.status == JobStatus.pending and jobs.as_utc(j.run_after) > jobs.now_utc()
        assert budget.summary(s).today == 0  # the rolled-back reservation left no charge
        assert s.query(IntegrationBlocker).filter_by(key="budget.daily").one()


def test_handler_error_retries_then_dead_letters():
    load_all()

    def boom(s, j):
        raise RuntimeError("transient")

    REGISTRY["test.boom"] = boom
    start_autopilot()
    with db.session_scope() as s:
        jid = jobs.enqueue(s, "test.boom", "b", max_attempts=2).id
    assert run_job(jid) == "retrying"
    with db.session_scope() as s:
        s.get(Job, jid).run_after = jobs.now_utc()
    assert run_job(jid) == "failed"
