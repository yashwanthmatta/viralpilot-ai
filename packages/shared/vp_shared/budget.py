"""Cost Optimization agent: hard spending limits.

Rule: no paid call runs without a reservation. ``reserve()`` checks the
estimate against the daily, monthly and per-item ceilings *including other
outstanding reservations*, inside a row lock on BudgetSettings so two workers
can't both squeeze under the limit at once. If a ceiling would be crossed it
raises ``BudgetExceeded`` and the caller must not make the call.

When the daily or monthly ceiling is hit, autopilot keeps running free work
(polling feeds, recovering jobs) but every paid step is refused until the
next day/month, and a blocker is shown on the dashboard.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vp_shared.config import get_settings
from vp_shared.models import BudgetSettings, CostEntry, CostEntryStatus


class BudgetExceeded(Exception):
    def __init__(self, scope: str, limit: float, would_be: float):
        self.scope, self.limit, self.would_be = scope, limit, would_be
        super().__init__(f"{scope} budget ${limit:.2f} would be exceeded (would reach ${would_be:.2f})")


def get_budget(s: Session, *, lock: bool = False) -> BudgetSettings:
    q = select(BudgetSettings).where(BudgetSettings.id == 1)
    if lock:
        q = q.with_for_update()
    row = s.execute(q).scalar_one_or_none()
    if row is None:
        cfg = get_settings()
        row = BudgetSettings(
            id=1,
            daily_limit_usd=cfg.default_daily_limit_usd,
            monthly_limit_usd=cfg.default_monthly_limit_usd,
            max_videos_per_day=cfg.default_max_videos_per_day,
        )
        s.add(row)
        s.flush()
    return row


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(now: datetime) -> datetime:
    return _day_start(now).replace(day=1)


def _spent(s: Session, since: datetime, item_id: int | None = None) -> float:
    q = select(func.coalesce(func.sum(CostEntry.amount_usd), 0.0)).where(
        CostEntry.status != CostEntryStatus.released,
    )
    if item_id is not None:
        q = q.where(CostEntry.item_id == item_id)
    else:
        q = q.where(CostEntry.created_at >= since)
    return float(s.execute(q).scalar_one())


@dataclass
class SpendSummary:
    today: float
    month: float
    daily_limit: float
    monthly_limit: float

    @property
    def daily_exhausted(self) -> bool:
        return self.today >= self.daily_limit

    @property
    def monthly_exhausted(self) -> bool:
        return self.month >= self.monthly_limit


def summary(s: Session, now: datetime | None = None) -> SpendSummary:
    now = now or datetime.now(timezone.utc)
    b = get_budget(s)
    return SpendSummary(
        today=_spent(s, _day_start(now)),
        month=_spent(s, _month_start(now)),
        daily_limit=b.daily_limit_usd,
        monthly_limit=b.monthly_limit_usd,
    )


def reserve(
    s: Session,
    *,
    category: str,
    estimate_usd: float,
    description: str = "",
    item_id: int | None = None,
    job_id: int | None = None,
    now: datetime | None = None,
) -> CostEntry:
    if estimate_usd < 0:
        raise ValueError("estimate must be >= 0")
    now = now or datetime.now(timezone.utc)
    b = get_budget(s, lock=True)
    today = _spent(s, _day_start(now)) + estimate_usd
    if today > b.daily_limit_usd + 1e-9:
        raise BudgetExceeded("daily", b.daily_limit_usd, today)
    month = _spent(s, _month_start(now)) + estimate_usd
    if month > b.monthly_limit_usd + 1e-9:
        raise BudgetExceeded("monthly", b.monthly_limit_usd, month)
    if item_id is not None:
        per_item = _spent(s, now, item_id=item_id) + estimate_usd
        if per_item > b.per_item_limit_usd + 1e-9:
            raise BudgetExceeded("per-video", b.per_item_limit_usd, per_item)
    entry = CostEntry(
        category=category,
        description=description,
        amount_usd=estimate_usd,
        status=CostEntryStatus.reserved,
        item_id=item_id,
        job_id=job_id,
        created_at=now,
    )
    s.add(entry)
    s.flush()
    return entry


def commit(s: Session, entry: CostEntry, actual_usd: float | None = None) -> None:
    if actual_usd is not None:
        entry.amount_usd = actual_usd
    entry.status = CostEntryStatus.committed
    s.flush()


def release(s: Session, entry: CostEntry) -> None:
    entry.status = CostEntryStatus.released
    s.flush()


@contextmanager
def spend(s: Session, **kwargs) -> Iterator[CostEntry]:
    """Reserve, run the block, commit. On exception the reservation is
    *committed at the estimate* (a failed API call may still be billed), so
    the ledger never under-counts. Set ``entry.amount_usd`` inside the block
    to record the real cost."""
    entry = reserve(s, **kwargs)
    try:
        yield entry
    finally:
        commit(s, entry)
