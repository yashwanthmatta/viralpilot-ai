"""Stage handlers, keyed by job kind.

Each handler takes (session, job) and either returns normally (job
succeeded), or raises StageBlocked / RetryLater / BudgetExceeded / any other
exception (retried with backoff). Handlers must be idempotent: a job can run
again after a crash, so they check current state before acting.
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session
from vp_shared.models import Job

Handler = Callable[[Session, Job], None]
REGISTRY: dict[str, Handler] = {}


def stage(kind: str) -> Callable[[Handler], Handler]:
    def wrap(fn: Handler) -> Handler:
        REGISTRY[kind] = fn
        return fn

    return wrap


def load_all() -> dict[str, Handler]:
    from . import acquisition, not_yet_built, publishing, video  # noqa: F401

    return REGISTRY
