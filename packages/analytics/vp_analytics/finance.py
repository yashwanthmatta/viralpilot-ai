"""Financial rollups and milestone planning.

Confirmed revenue, pending revenue and estimates are always separate fields.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from vp_shared.models import (
    Campaign,
    Clip,
    ClipStage,
    CostEntry,
    CostEntryStatus,
    MetricSnapshot,
    Publication,
    PublicationStatus,
    RevenueEntry,
    RevenueStatus,
    SocialAccount,
)

MILESTONES = [1, 100, 1_000, 5_000, 10_000, 25_000, 50_000, 100_000]
ASSUMED_EFFECTIVE_RPM = 1.50       # $ per 1,000 qualified views, after fees
ASSUMED_VIEWS_PER_VIDEO = 20_000
ASSUMED_COST_PER_VIDEO = 0.30
ASSUMED_POSTS_PER_CHANNEL_DAY = 3
FIXED_MONTHLY_COST = 35.0          # hosting estimate; see DEPLOYMENT.md


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def revenue_sum(s: Session, status: RevenueStatus, since: datetime | None = None, **where) -> float:
    q = select(func.coalesce(func.sum(RevenueEntry.amount), 0.0)).where(RevenueEntry.status == status)
    if since is not None:
        q = q.where(RevenueEntry.occurred_at >= since)
    for k, v in where.items():
        q = q.where(getattr(RevenueEntry, k) == v)
    return float(s.execute(q).scalar_one())


def cost_sum(s: Session, since: datetime | None = None) -> float:
    q = select(func.coalesce(func.sum(CostEntry.amount_usd), 0.0)).where(CostEntry.status != CostEntryStatus.released)
    if since is not None:
        q = q.where(CostEntry.created_at >= since)
    return float(s.execute(q).scalar_one())


def latest_views(s: Session) -> dict[int, int]:
    latest = (select(MetricSnapshot.publication_id, func.max(MetricSnapshot.id).label("mid"))
              .group_by(MetricSnapshot.publication_id).subquery())
    rows = s.execute(select(MetricSnapshot.publication_id, MetricSnapshot.views)
                     .join(latest, MetricSnapshot.id == latest.c.mid)).all()
    return {pid: int(v or 0) for pid, v in rows}


def overview(s: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    m0 = _month_start(now)
    confirmed_month = revenue_sum(s, RevenueStatus.confirmed, m0)
    cost_month = cost_sum(s, m0)
    views = latest_views(s)
    published = s.execute(select(func.count(Publication.id)).where(
        Publication.status == PublicationStatus.published)).scalar_one()
    return {
        "confirmed_today": revenue_sum(s, RevenueStatus.confirmed, day0),
        "confirmed_month": confirmed_month,
        "confirmed_all_time": revenue_sum(s, RevenueStatus.confirmed),
        "pending": revenue_sum(s, RevenueStatus.pending),
        "costs_month": cost_month,
        "costs_all_time": cost_sum(s),
        "net_month_confirmed": round(confirmed_month - cost_month, 2),
        "qualified_views_total": sum(views.values()),
        "videos_published": int(published),
        "videos_generated": int(s.execute(select(func.count(Clip.id)).where(Clip.render_path != "")).scalar_one()),
        "progress_to_100k": round(min(confirmed_month / 100_000, 1.0), 6),
        "next_milestone": next((m for m in MILESTONES if m > confirmed_month), None),
        "first_dollar_reached": revenue_sum(s, RevenueStatus.confirmed) >= 1,
    }


def by_dimension(s: Session) -> dict:
    """Confirmed and pending revenue per platform, account and campaign."""
    def group(col, join=None):
        q = select(col, RevenueEntry.status, func.sum(RevenueEntry.amount))
        if join is not None:
            q = q.join(*join)
        q = q.group_by(col, RevenueEntry.status)
        out: dict = {}
        for key, st, amt in s.execute(q).all():
            d = out.setdefault(str(key), {"confirmed": 0.0, "pending": 0.0})
            if st.value in d:
                d[st.value] += float(amt or 0)
        return out

    return {
        "by_stream": group(RevenueEntry.stream),
        "by_platform": group(Publication.platform, (Publication, Publication.id == RevenueEntry.publication_id)),
        "by_account": group(SocialAccount.display_name, (SocialAccount, SocialAccount.id == RevenueEntry.account_id)),
        "by_campaign": group(Campaign.name, (Campaign, Campaign.id == RevenueEntry.campaign_id)),
    }


@dataclass
class MilestoneRow:
    monthly_revenue: int
    qualified_views_per_month: int
    videos_per_month: int
    videos_per_day: float
    campaign_budget_needed: int
    variable_cost: int
    operating_cost: int
    est_profit: int
    channels_needed: int


def milestone_plan(s: Session) -> dict:
    """Uses our own measured rates once there's enough data, else labelled assumptions."""
    views = latest_views(s)
    paid_pubs = s.execute(select(RevenueEntry.publication_id, func.sum(RevenueEntry.amount))
                          .where(RevenueEntry.status == RevenueStatus.confirmed,
                                 RevenueEntry.publication_id.isnot(None))
                          .group_by(RevenueEntry.publication_id)).all()
    basis = "assumptions"
    rpm, vpv = ASSUMED_EFFECTIVE_RPM, ASSUMED_VIEWS_PER_VIDEO
    if len(paid_pubs) >= 10:
        rev = sum(float(a) for _, a in paid_pubs)
        v = sum(views.get(pid, 0) for pid, _ in paid_pubs)
        if v > 0:
            rpm, vpv, basis = rev / v * 1000, v / len(paid_pubs), f"measured from {len(paid_pubs)} paid videos"
    rendered = s.execute(select(func.count(Clip.id)).where(Clip.stage != ClipStage.proposed)).scalar_one()
    cpv = cost_sum(s) / rendered if rendered >= 10 else ASSUMED_COST_PER_VIDEO
    rows = []
    for m in MILESTONES:
        qv = m / rpm * 1000
        vids = max(1, round(qv / vpv))
        var = vids * cpv
        op = var + FIXED_MONTHLY_COST
        rows.append(MilestoneRow(m, round(qv), vids, round(vids / 30, 1), round(m), round(var), round(op),
                                 round(m - op), max(1, round(vids / 30 / ASSUMED_POSTS_PER_CHANNEL_DAY + 0.49))))
    return {"basis": basis, "effective_rpm": round(rpm, 3), "views_per_video": round(vpv),
            "cost_per_video": round(cpv, 3), "label": "estimate", "rows": [asdict(r) for r in rows]}


def last_14d(s: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=14)
    vids = s.execute(select(func.count(Clip.id)).where(Clip.render_path != "", Clip.created_at >= since)).scalar_one()
    paid = s.execute(select(func.count(func.distinct(RevenueEntry.publication_id))).where(
        RevenueEntry.status == RevenueStatus.confirmed, RevenueEntry.occurred_at >= since)).scalar_one()
    return {"videos": int(vids), "paid_videos": int(paid),
            "confirmed": revenue_sum(s, RevenueStatus.confirmed, since),
            "pending": revenue_sum(s, RevenueStatus.pending, since), "cost": cost_sum(s, since)}
