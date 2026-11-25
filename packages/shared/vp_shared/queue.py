"""Celery configuration shared by the API (producer) and worker (consumer)."""
from __future__ import annotations

from celery import Celery

from vp_shared.config import get_settings


def make_celery() -> Celery:
    cfg = get_settings()
    app = Celery("viralpilot", broker=cfg.redis_url)
    app.conf.update(
        task_acks_late=True,                 # message is only removed after the task finishes
        task_reject_on_worker_lost=True,     # a killed worker's message is redelivered
        worker_prefetch_multiplier=1,        # long video jobs: take one at a time
        task_ignore_result=True,             # results live in Postgres, not Redis
        broker_transport_options={"visibility_timeout": cfg.job_lease_s + 300},
        broker_connection_retry_on_startup=True,
        timezone="UTC",
        beat_schedule={
            "supervisor-tick": {"task": "vp.supervisor_tick", "schedule": float(cfg.supervisor_interval_s)},
        },
    )
    return app
