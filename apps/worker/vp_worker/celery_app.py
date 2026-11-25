"""Celery worker entry point.

Run (one always-on process, beat embedded to keep hosting cheap):
    celery -A vp_worker.celery_app worker -B --loglevel=INFO --concurrency=1

Beat fires the supervisor tick every SUPERVISOR_INTERVAL_S. If this process
dies the host restarts it; interrupted jobs come back through lease recovery.
"""
from __future__ import annotations

import logging

from celery.signals import worker_init
from vp_agents import supervisor, worker
from vp_shared import db
from vp_shared.logging import configure_logging
from vp_shared.queue import make_celery

app = make_celery()
log = logging.getLogger("vp.worker")


@worker_init.connect
def _init(**_):
    configure_logging()
    db.create_all()  # no-op when migrations already ran


@app.task(name="vp.run_job")
def run_job(job_id: int) -> str:
    return worker.run_job(job_id)


@app.task(name="vp.supervisor_tick")
def supervisor_tick() -> dict:
    return supervisor.tick()
