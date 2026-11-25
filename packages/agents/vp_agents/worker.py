"""Job execution. Called by RQ workers with a job id (Redis carries only ids)."""
from __future__ import annotations

import logging
import traceback

from vp_shared import db, jobs
from vp_shared.budget import BudgetExceeded
from vp_shared.events import autopilot, decide, raise_blocker
from vp_shared.jobs import RetryLater, StageBlocked
from vp_shared.models import Job

from vp_agents import dispatch
from vp_agents.stages import load_all

log = logging.getLogger("viralpilot.worker")

# Jobs that must run even while autopilot is stopped (none in phase 1:
# STOP means stop everything that touches the outside world).
ALWAYS_RUN: set[str] = set()


def _seconds_to_next_utc_day() -> int:
    n = jobs.now_utc()
    tomorrow = n.replace(hour=0, minute=5, second=0, microsecond=0)
    secs = int((tomorrow - n).total_seconds())
    return secs if secs > 0 else secs + 86400


def run_job(job_id: int) -> str:
    try:
        return _run(job_id)
    finally:
        dispatch.clear_dispatch_marker(job_id)


def _run(job_id: int) -> str:
    handlers = load_all()
    with db.session_scope() as s:
        job = jobs.claim(s, job_id)
        if job is None:
            return "not-claimed"  # someone else has it, or it's not due
        kind = job.kind
        if kind not in ALWAYS_RUN and not autopilot(s).enabled:
            jobs.release_to_pending(s, job)
            return "paused"

    handler = handlers.get(kind)
    s = db.new_session()
    outcome = "succeeded"
    try:
        job = s.get(Job, job_id)
        if handler is None:
            raise RuntimeError(f"no handler for job kind {kind!r}")
        handler(s, job)
        job = s.get(Job, job_id)  # handler may have committed
        jobs.succeed(s, job)
        s.commit()
        return outcome
    except Exception as exc:  # noqa: BLE001 — every failure is recorded
        s.rollback()
        err = exc
        tb = traceback.format_exc()
    finally:
        s.close()

    with db.session_scope() as s2:
        job = s2.get(Job, job_id)
        if isinstance(err, StageBlocked):
            jobs.block(s2, job, err.title)
            raise_blocker(s2, err.key, err.title, err.detail)
            return "blocked"
        if isinstance(err, BudgetExceeded):
            delay = _seconds_to_next_utc_day() if err.scope != "per-video" else 0
            if err.scope == "per-video":
                jobs.fail(s2, job, str(err))
                job.status = jobs.JobStatus.failed  # never retry a per-video overrun
                decide(s2, "Cost Optimization Specialist", "stopped_item_over_budget", str(err))
                return "failed"
            jobs.retry_later(s2, job, str(err), delay)
            raise_blocker(s2, f"budget.{err.scope}", f"{err.scope.capitalize()} budget reached",
                          f"{err}. Paid steps resume automatically when the period resets.")
            decide(s2, "Cost Optimization Specialist", "paused_paid_work", str(err))
            return "budget-wait"
        if isinstance(err, RetryLater):
            jobs.retry_later(s2, job, err.reason, err.delay_s)
            return "retry-later"
        log.warning("job %s (%s) failed: %s", job_id, kind, err)
        jobs.fail(s2, job, f"{type(err).__name__}: {err}\n{tb[-2000:]}")
        if job.status == jobs.JobStatus.failed:
            decide(s2, "Autonomous Supervisor", "job_dead_lettered", f"{kind} #{job_id}: {err}")
            return "failed"
        decide(s2, "Autonomous Supervisor", "job_retry_scheduled",
               f"{kind} #{job_id} attempt {job.attempts}: {err}")
        return "retrying"
