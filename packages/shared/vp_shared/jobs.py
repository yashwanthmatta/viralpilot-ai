"""Durable job queue (Autonomous Supervisor's core).

* ``enqueue`` is idempotent on ``dedupe_key``.
* ``claim`` takes a lease with a single conditional UPDATE, so two workers
  can never run the same job, on Postgres or SQLite.
* A worker that dies leaves an expired lease; ``recover_expired`` puts the
  job back to pending, which is how unfinished work resumes after restarts.
* Failures retry with exponential backoff up to ``max_attempts``, then the
  job is dead-lettered (status=failed) and shown on the dashboard.
* ``StageBlocked`` marks a job blocked (an external dependency, not a bug);
  it is not retried until the blocker is cleared.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from vp_shared.config import get_settings
from vp_shared.models import Job, JobStatus


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; normalise so comparisons work everywhere."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class StageBlocked(Exception):
    """Raised by a stage that cannot proceed for an external reason."""

    def __init__(self, key: str, title: str, detail: str = ""):
        self.key, self.title, self.detail = key, title, detail
        super().__init__(title)


class RetryLater(Exception):
    """Raised for transient conditions (rate limits, budget exhausted for today)."""

    def __init__(self, reason: str, delay_s: int):
        self.reason, self.delay_s = reason, delay_s
        super().__init__(reason)


def enqueue(
    s: Session,
    kind: str,
    dedupe_key: str,
    payload: dict | None = None,
    *,
    run_after: datetime | None = None,
    max_attempts: int | None = None,
) -> Job | None:
    """Returns the new job, or None if a job with this key already exists."""
    existing = s.execute(select(Job).where(Job.dedupe_key == dedupe_key)).scalar_one_or_none()
    if existing is not None:
        return None
    job = Job(
        kind=kind,
        dedupe_key=dedupe_key,
        payload=payload or {},
        run_after=run_after or now_utc(),
        max_attempts=max_attempts or get_settings().job_max_attempts,
    )
    try:
        with s.begin_nested():
            s.add(job)
            s.flush()
    except IntegrityError:
        return None  # lost a race with another enqueuer
    return job


def due_job_ids(s: Session, limit: int = 100, now: datetime | None = None) -> list[int]:
    now = now or now_utc()
    q = (
        select(Job.id)
        .where(Job.status == JobStatus.pending, Job.run_after <= now)
        .order_by(Job.run_after)
        .limit(limit)
    )
    return list(s.execute(q).scalars())


def claim(s: Session, job_id: int, now: datetime | None = None) -> Job | None:
    now = now or now_utc()
    lease = now + timedelta(seconds=get_settings().job_lease_s)
    res = s.execute(
        update(Job)
        .where(Job.id == job_id, Job.status == JobStatus.pending, Job.run_after <= now)
        .values(status=JobStatus.running, lease_expires_at=lease, attempts=Job.attempts + 1)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        return None
    s.flush()
    job = s.get(Job, job_id)
    s.refresh(job)
    return job


def succeed(s: Session, job: Job) -> None:
    job.status = JobStatus.succeeded
    job.lease_expires_at = None
    job.finished_at = now_utc()
    job.last_error = ""


def fail(s: Session, job: Job, error: str, now: datetime | None = None) -> None:
    now = now or now_utc()
    job.last_error = error[:4000]
    job.lease_expires_at = None
    if job.attempts >= job.max_attempts:
        job.status = JobStatus.failed
        job.finished_at = now
    else:
        backoff = min(60 * (2 ** (job.attempts - 1)), 3600)
        job.status = JobStatus.pending
        job.run_after = now + timedelta(seconds=backoff)


def retry_later(s: Session, job: Job, reason: str, delay_s: int, now: datetime | None = None) -> None:
    """Transient wait that does not count as a failed attempt."""
    now = now or now_utc()
    job.status = JobStatus.pending
    job.attempts = max(job.attempts - 1, 0)
    job.lease_expires_at = None
    job.last_error = reason
    job.run_after = now + timedelta(seconds=delay_s)


def block(s: Session, job: Job, reason: str) -> None:
    job.status = JobStatus.blocked
    job.attempts = max(job.attempts - 1, 0)
    job.lease_expires_at = None
    job.last_error = reason


def release_to_pending(s: Session, job: Job) -> None:
    """Autopilot was stopped while this job was claimed: put it back untouched."""
    job.status = JobStatus.pending
    job.attempts = max(job.attempts - 1, 0)
    job.lease_expires_at = None


def recover_expired(s: Session, now: datetime | None = None) -> int:
    """Jobs whose worker died mid-run go back to pending (counts as an attempt)."""
    now = now or now_utc()
    stuck = s.execute(
        select(Job).where(Job.status == JobStatus.running, Job.lease_expires_at < now)
    ).scalars().all()
    for job in stuck:
        fail(s, job, "worker lease expired (worker crashed or restarted); retrying", now)
    return len(stuck)


def unblock(s: Session, kind_prefix: str | None = None) -> int:
    q = select(Job).where(Job.status == JobStatus.blocked)
    if kind_prefix:
        q = q.where(or_(Job.kind == kind_prefix, Job.kind.startswith(kind_prefix)))
    jobs = s.execute(q).scalars().all()
    for j in jobs:
        j.status = JobStatus.pending
        j.run_after = now_utc()
    return len(jobs)
