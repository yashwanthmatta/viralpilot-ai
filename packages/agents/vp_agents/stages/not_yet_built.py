"""Stages that later phases implement.

They are registered now so the pipeline is wired end to end and the
dashboard shows honestly where work stops, instead of silently dropping
jobs or pretending to succeed.
"""
from __future__ import annotations

from sqlalchemy.orm import Session
from vp_shared.jobs import StageBlocked
from vp_shared.models import Job

from . import stage

PENDING_STAGES = {
    "analytics.publication": ("Phase 5", "Performance metrics collection"),
    "generate.original": ("Phase 7", "Original faceless video generation"),
}


def _make(kind: str):
    phase, title = PENDING_STAGES[kind]

    def handler(s: Session, job: Job) -> None:
        raise StageBlocked(
            key=f"stage.{kind}",
            title=f"{title} is not built yet ({phase})",
            detail="Jobs wait here and resume automatically once this stage ships.",
        )

    return handler


for _kind in PENDING_STAGES:
    stage(_kind)(_make(_kind))
