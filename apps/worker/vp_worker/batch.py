"""Batch mode: one scheduled run does a supervisor tick and works through
every due job, then exits. No Redis, no always-on server.

This is what the free GitHub Actions schedule runs
(.github/workflows/autopilot.yml):

    python -m vp_worker.batch --max-seconds 1500

Job state lives in PostgreSQL exactly as in the always-on mode, so a run
that is cut off mid-job is recovered by lease expiry on the next run.
Media persists between runs in MEDIA_DIR (restored from the Actions cache).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import timedelta

from vp_agents import dispatch, supervisor, worker
from vp_shared import db, jobs
from vp_shared.config import get_settings
from vp_shared.logging import configure_logging
from vp_shared.models import Clip, ClipStage, ContentItem, ItemStage, Publication, PublicationStatus

log = logging.getLogger("vp.batch")

# Clips waiting to be posted keep their render; everything else is pruned
# after this many days so the cache stays small.
KEEP_DAYS = int(os.environ.get("MEDIA_KEEP_DAYS", "10"))


def prune_media(now=None) -> int:
    """Delete media nothing still needs. Returns bytes freed."""
    now = now or jobs.now_utc()
    cutoff = now - timedelta(days=KEEP_DAYS)
    freed = 0
    with db.session_scope() as s:
        pending_clip_ids = {cid for (cid,) in s.query(Publication.clip_id).filter(
            Publication.status.in_([PublicationStatus.scheduled, PublicationStatus.publishing]))}
        for c in s.query(Clip).filter(Clip.render_path != ""):
            done = c.stage in (ClipStage.qc_failed, ClipStage.discarded) or (
                c.stage == ClipStage.ready and c.id not in pending_clip_ids and jobs.as_utc(c.created_at) < cutoff)
            if done:
                for p in (c.render_path, c.cover_path):
                    freed += _rm(p)
                c.render_path = c.render_path if os.path.exists(c.render_path) else ""
        for it in s.query(ContentItem).filter(ContentItem.local_path != ""):
            finished = it.stage in (ItemStage.clipped, ItemStage.discarded) and not s.query(Clip).filter(
                Clip.item_id == it.id, Clip.stage.in_([ClipStage.proposed, ClipStage.rendered])).count()
            if finished and jobs.as_utc(it.discovered_at) < cutoff:
                freed += _rm(it.local_path)
    return freed


def _rm(path: str) -> int:
    root = os.path.realpath(get_settings().media_dir)
    real = os.path.realpath(path or "")
    if not path or not os.path.isfile(real) or os.path.commonpath([root, real]) != root:
        return 0
    size = os.path.getsize(real)
    os.remove(real)
    return size


def run(max_seconds: float) -> dict:
    deadline = time.monotonic() + max_seconds
    queue: list[int] = []
    dispatch.set_dispatcher(queue.append)
    outcomes: dict[str, int] = {}
    ticks = 0
    try:
        while time.monotonic() < deadline:
            queue.clear()
            supervisor.tick()
            ticks += 1
            if not queue:
                break
            progressed = False
            for job_id in list(queue):
                if time.monotonic() >= deadline:
                    break
                res = worker.run_job(job_id)
                outcomes[res] = outcomes.get(res, 0) + 1
                progressed = progressed or res not in ("not-claimed", "paused")
            # Jobs finished in this pass may have queued follow-ups that are
            # already due (transcribe -> clip -> edit -> qc -> metadata), so go again.
            if not progressed or ticks >= 200:
                break
    finally:
        dispatch.set_dispatcher(None)
    freed = prune_media()
    return {"ticks": ticks, "outcomes": outcomes, "media_freed_mb": round(freed / 1e6, 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Run one ViralPilot batch")
    ap.add_argument("--max-seconds", type=float, default=1500)
    args = ap.parse_args()
    configure_logging()
    db.create_all()
    report = run(args.max_seconds)
    print(json.dumps(report))  # noqa: T201 - shown in the Actions log


if __name__ == "__main__":
    main()
