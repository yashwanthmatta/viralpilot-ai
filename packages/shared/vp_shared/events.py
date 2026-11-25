"""Dashboard feed helpers: agent decisions and integration blockers."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from vp_shared.jobs import now_utc
from vp_shared.models import AgentDecision, AutopilotState, IntegrationBlocker


def decide(s: Session, agent: str, action: str, detail: str = "", *, item_id=None, clip_id=None) -> None:
    s.add(AgentDecision(agent=agent, action=action, detail=detail[:4000], item_id=item_id, clip_id=clip_id))


def raise_blocker(s: Session, key: str, title: str, detail: str = "") -> None:
    row = s.execute(select(IntegrationBlocker).where(IntegrationBlocker.key == key)).scalar_one_or_none()
    if row is None:
        s.add(IntegrationBlocker(key=key, title=title, detail=detail))
    else:
        row.title, row.detail, row.resolved, row.last_seen_at = title, detail, False, now_utc()
    s.flush()


def resolve_blocker(s: Session, key: str) -> None:
    row = s.execute(select(IntegrationBlocker).where(IntegrationBlocker.key == key)).scalar_one_or_none()
    if row is not None and not row.resolved:
        row.resolved = True
        row.last_seen_at = now_utc()


def autopilot(s: Session, *, lock: bool = False) -> AutopilotState:
    q = select(AutopilotState).where(AutopilotState.id == 1)
    if lock:
        q = q.with_for_update()
    row = s.execute(q).scalar_one_or_none()
    if row is None:
        row = AutopilotState(id=1, enabled=False, reason="never started")
        s.add(row)
        s.flush()
    return row


def set_autopilot(s: Session, enabled: bool, reason: str) -> AutopilotState:
    st = autopilot(s, lock=True)
    st.enabled = enabled
    st.reason = reason
    st.changed_at = now_utc()
    decide(s, "Autonomous Supervisor", "autopilot_started" if enabled else "autopilot_stopped", reason)
    return st
