"""Agent 10, Autonomous Supervisor.

Runs every ``SUPERVISOR_INTERVAL_S``, fired by Celery beat inside the
always-on worker process. Each tick is cheap (no AI calls):

1. recover jobs whose worker died (expired lease)  -> resumes unfinished work
2. if autopilot is on: schedule source polling on its interval
3. refresh integration blockers (sources, accounts, budget)
4. send every due job id to the Redis queue
5. record a heartbeat the dashboard shows as worker health
"""
from __future__ import annotations

import logging
from datetime import timedelta

import vp_publishing
from sqlalchemy import select
from vp_shared import budget, db, jobs
from vp_shared.config import get_settings
from vp_shared.events import autopilot, decide, raise_blocker, resolve_blocker
from vp_shared.models import SocialAccount, Source

from vp_agents import dispatch

log = logging.getLogger("viralpilot.supervisor")


def tick() -> dict:
    cfg = get_settings()
    report: dict = {}
    with db.session_scope() as s:
        now = jobs.now_utc()
        st = autopilot(s)
        report["recovered"] = jobs.recover_expired(s, now)
        if report["recovered"]:
            decide(s, "Autonomous Supervisor", "recovered_jobs",
                   f"{report['recovered']} interrupted job(s) put back in the queue")

        sources = s.execute(select(Source).where(Source.enabled.is_(True))).scalars().all()
        if not sources:
            raise_blocker(s, "sources.none", "No authorised content sources",
                          "Add at least one source you own or that is licensed for commercial reuse.")
        else:
            resolve_blocker(s, "sources.none")

        accounts = s.execute(select(SocialAccount)).scalars().all()
        if not accounts:
            raise_blocker(s, "accounts.none", "No social accounts connected",
                          "Connect an account and allow publishing to it.")
        else:
            resolve_blocker(s, "accounts.none")
        for acc in accounts:
            adapter = vp_publishing.get(acc.platform)
            if adapter is None:
                continue
            a = adapter.availability(acc)
            if a.ok:
                resolve_blocker(s, f"platform.{acc.platform}")
            else:
                raise_blocker(s, a.blocker_key, f"{acc.platform}: publishing blocked", a.reason)

        spend = budget.summary(s, now)
        for scope, exhausted in (("daily", spend.daily_exhausted), ("monthly", spend.monthly_exhausted)):
            if not exhausted:
                resolve_blocker(s, f"budget.{scope}")

        scheduled = 0
        if st.enabled:
            last = jobs.as_utc(st.last_discovery_at)
            if last is None or now - last >= timedelta(seconds=cfg.discovery_interval_s):
                bucket = int(now.timestamp() // cfg.discovery_interval_s)
                for src in sources:
                    if jobs.enqueue(s, "discover.source", f"discover:{src.id}:{bucket}", {"source_id": src.id}):
                        scheduled += 1
                st.last_discovery_at = now
        report["discovery_jobs"] = scheduled
        st.last_tick_at = now
        due = jobs.due_job_ids(s, limit=200) if st.enabled else []

    sent = 0
    for job_id in due:
        try:
            if dispatch.dispatch(job_id):
                sent += 1
        except Exception:  # Redis down: jobs stay pending in the DB and go next tick
            log.exception("dispatch failed for job %s", job_id)
            break
    report["dispatched"] = sent
    return report
