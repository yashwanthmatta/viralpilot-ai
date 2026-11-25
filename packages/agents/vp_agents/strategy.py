"""Daily strategy run: scaling volume and pruning campaigns from real results."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from vp_analytics import finance, scaling
from vp_shared import budget
from vp_shared.events import decide
from vp_shared.models import Campaign, CampaignStatus, CampaignSubmission, SocialAccount, SubmissionStatus

from vp_agents.stages import stage

AGENT = "Growth Analyst"
MIN_RESOLVED = 5
MIN_APPROVAL = 0.2


@stage("strategy.daily")
def strategy_daily(s: Session, job) -> None:
    b = budget.get_budget(s, lock=True)
    f = finance.last_14d(s)
    unhealthy = len(s.execute(select(SocialAccount.id).where(SocialAccount.publishing_allowed.is_(True),
                                                             SocialAccount.health != "ok")).all())
    d = scaling.decide(scaling.ScalingInput(
        current_per_day=b.max_videos_per_day, ceiling=b.max_videos_ceiling, floor=1,
        videos_14d=f["videos"], paid_videos_14d=f["paid_videos"], confirmed_revenue_14d=f["confirmed"],
        pending_revenue_14d=f["pending"], cost_14d=f["cost"], unhealthy_accounts=unhealthy))
    if d.new_per_day != b.max_videos_per_day:
        b.max_videos_per_day = d.new_per_day
    decide(s, AGENT, f"volume_{d.action}", f"{d.new_per_day} videos/day: {d.reason}")

    for c in s.execute(select(Campaign).where(Campaign.status == CampaignStatus.active)).scalars():
        subs = s.execute(select(CampaignSubmission.status).where(CampaignSubmission.campaign_id == c.id)).scalars().all()
        resolved = [x for x in subs if x in (SubmissionStatus.approved, SubmissionStatus.rejected, SubmissionStatus.paid)]
        if len(resolved) >= MIN_RESOLVED:
            rate = sum(1 for x in resolved if x != SubmissionStatus.rejected) / len(resolved)
            if rate < MIN_APPROVAL:
                c.status, c.status_reason = CampaignStatus.rejected, f"approval rate {rate:.0%} on {len(resolved)} clips"
                decide(s, AGENT, "campaign_dropped", f"{c.name}: {c.status_reason}")
