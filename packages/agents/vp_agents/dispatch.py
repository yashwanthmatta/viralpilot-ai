"""Queue dispatch via Celery (Redis broker).

The broker is only a wake-up channel: job state lives in PostgreSQL, so if
Redis is flushed or a message is lost, the supervisor re-sends every due job
on its next tick. Workers claim jobs atomically in the database, so a
duplicate message can never run a job twice.
"""
from __future__ import annotations

import logging
from typing import Callable

from vp_shared.config import get_settings

TASK_NAME = "vp.run_job"
_override: Callable[[int], None] | None = None
_celery = None


def celery_client():
    global _celery
    if _celery is None:
        from vp_shared.queue import make_celery

        _celery = make_celery()
    return _celery


def set_dispatcher(fn: Callable[[int], None] | None) -> None:
    """Tests (and single-process dev mode) collect or run jobs inline."""
    global _override
    _override = fn


def _redis():
    import redis

    return redis.Redis.from_url(get_settings().redis_url)


def dispatch(job_id: int) -> bool:
    if _override is not None:
        _override(job_id)
        return True
    # Don't flood the broker with copies of a job that's already queued.
    if not _redis().set(f"vp:dispatched:{job_id}", "1", nx=True, ex=get_settings().job_lease_s):
        return False
    celery_client().send_task(TASK_NAME, args=[job_id])
    return True


def clear_dispatch_marker(job_id: int) -> None:
    if _override is None:
        try:
            _redis().delete(f"vp:dispatched:{job_id}")
        except Exception:  # marker expires on its own
            logging.getLogger("vp.dispatch").debug("could not clear marker for job %s", job_id)
