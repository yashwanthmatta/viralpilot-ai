"""Paid clipping campaigns: discovery adapters, eligibility, ranking, activation.

Adapters only use official APIs or feeds you have authorised:

* ``WhopBountyAdapter``  — Whop Bounties API (beta), clipping-type bounties the
  signed-in user can work. Needs WHOP_ACCESS_TOKEN (user OAuth token with
  ``bounty:basic:read`` and ``bounty:submission:create``).
* ``FeedAdapter``        — JSON feeds you authorise (CAMPAIGN_FEED_URLS), e.g.
  a direct partner's brief list. Schema in docs/campaign-feed.md.
* Manual entry (API / dashboard) for marketplaces without a public API
  (Content Rewards, Vyro, direct deals).
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from vp_analytics import profit
from vp_shared import netsafety
from vp_shared.events import decide, raise_blocker, resolve_blocker
from vp_shared.jobs import as_utc, enqueue, now_utc
from vp_shared.models import (
    Campaign,
    CampaignStatus,
    CampaignSubmission,
    CostEntry,
    CostEntryStatus,
    LicenseType,
    MetricSnapshot,
    Publication,
    PublicationStatus,
    RevenueEntry,
    RevenueStatus,
    SocialAccount,
    Source,
    SourceKind,
    SubmissionStatus,
)

AGENT = "Campaign Strategist"
SUPPORTED_PLATFORMS = {"youtube", "facebook", "instagram", "tiktok"}
MEDIA_EXT = re.compile(r"\.(mp4|mov|m4v|webm|mkv|mp3|m4a|wav)(\?|$)", re.I)
URL_RE = re.compile(r"https://[^\s)\]>\"']+")
PLATFORM_WORDS = {
    "youtube": "youtube", "shorts": "youtube", "tiktok": "tiktok", "instagram": "instagram", "reels": "instagram",
    "facebook": "facebook",
}
MAX_PLAUSIBLE_CPM = 25.0
MAX_PLAUSIBLE_FLAT = 1000.0


@dataclass
class CampaignData:
    provider: str
    external_id: str
    name: str
    creator: str = ""
    url: str = ""
    payout_model: str = "cpm"
    currency: str = "USD"
    rate_per_1k: float | None = None
    flat_reward: float | None = None
    budget_total: float | None = None
    budget_remaining: float | None = None
    min_payout: float | None = None
    max_payout_per_video: float | None = None
    platform_fee_pct: float = 0.0
    ends_at: datetime | None = None
    platforms: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    requirements: str = ""
    footage_urls: list[str] = field(default_factory=list)
    rights_note: str = ""
    submission_method: str = "manual"
    automation_allowed: bool | None = None
    status_hint: str = "open"
    raw: dict = field(default_factory=dict)


class Adapter(Protocol):
    provider: str

    def configured(self) -> bool: ...

    def discover(self) -> list[CampaignData]: ...


def _platforms_from_text(text: str) -> list[str]:
    t = text.lower()
    return sorted({p for w, p in PLATFORM_WORDS.items() if re.search(rf"\b{w}\b", t)})


def _footage_from_text(text: str) -> list[str]:
    return [u for u in URL_RE.findall(text or "") if MEDIA_EXT.search(u) or u.rstrip("/").endswith((".rss", "/feed", ".xml"))]


class WhopBountyAdapter:
    provider = "whop_bounty"
    base = "https://api.whop.com/api/v1"

    def configured(self) -> bool:
        return bool(os.environ.get("WHOP_ACCESS_TOKEN"))

    def _get(self, path: str, params: dict) -> dict:
        import httpx

        r = httpx.get(f"{self.base}{path}", params=params, timeout=30, headers={
            "Authorization": f"Bearer {os.environ['WHOP_ACCESS_TOKEN']}",
            "Api-Version-Date": os.environ.get("WHOP_API_VERSION_DATE", "2026-01-01"),
        })
        r.raise_for_status()
        return r.json()

    def discover(self) -> list[CampaignData]:
        params = {"status": "open", "business_goal_type": "clipping", "first": 100}
        if os.environ.get("OPERATOR_COUNTRY"):
            params["country"] = os.environ["OPERATOR_COUNTRY"]
        out = []
        for b in self._get("/bounties", params).get("data", []):
            desc = b.get("description") or ""
            budget = b.get("budget_amount")
            paid = b.get("gross_paid_out_amount") or 0
            out.append(CampaignData(
                provider=self.provider, external_id=str(b["id"]), name=b.get("title") or b["id"],
                creator=((b.get("poster") or {}).get("name") or ""), url=f"https://whop.com/bounties/{b['id']}",
                payout_model="flat", currency=(b.get("currency") or "usd").upper(),
                flat_reward=b.get("net_reward_amount") or b.get("gross_reward_amount"),
                budget_total=budget, budget_remaining=(budget - paid) if budget is not None else None,
                countries=b.get("allowed_country_codes") or [], requirements=desc,
                platforms=_platforms_from_text(desc), footage_urls=_footage_from_text(desc),
                rights_note="Footage supplied or authorised by the bounty poster",
                submission_method="api", automation_allowed=True,
                status_hint=b.get("status") or "open", raw=b,
            ))
        return out

    def submit(self, bounty_id: str, post_url: str, caption: str = "") -> dict:
        import httpx

        r = httpx.post(f"{self.base}/bounty_submissions", timeout=30, headers={
            "Authorization": f"Bearer {os.environ['WHOP_ACCESS_TOKEN']}",
            "Idempotency-Key": "vp-" + hashlib.sha256(f"{bounty_id}|{post_url}".encode()).hexdigest()[:40],
        }, json={"bounty_id": bounty_id, "deliverable": {"urls": [post_url], "caption": caption[:500] or None}})
        r.raise_for_status()
        return r.json()

    def submission_status(self, submission_id: str) -> dict:
        return self._get(f"/bounty_submissions/{submission_id}", {})


class FeedAdapter:
    """JSON array of campaign objects at each URL in CAMPAIGN_FEED_URLS."""

    provider = "feed"

    def configured(self) -> bool:
        return bool(os.environ.get("CAMPAIGN_FEED_URLS"))

    def discover(self) -> list[CampaignData]:
        out = []
        for url in [u.strip() for u in os.environ.get("CAMPAIGN_FEED_URLS", "").split(",") if u.strip()]:
            data = netsafety.safe_get(url).json()
            for c in data if isinstance(data, list) else data.get("campaigns", []):
                out.append(from_dict({**c, "provider": c.get("provider", "feed")}))
        return out


def from_dict(c: dict) -> CampaignData:
    ends = c.get("ends_at")
    return CampaignData(
        provider=str(c.get("provider", "manual"))[:40], external_id=str(c["external_id"])[:200],
        name=str(c["name"])[:300], creator=str(c.get("creator", ""))[:200], url=str(c.get("url", ""))[:1000],
        payout_model=c.get("payout_model", "cpm"), currency=c.get("currency", "USD"),
        rate_per_1k=c.get("rate_per_1k"), flat_reward=c.get("flat_reward"),
        budget_total=c.get("budget_total"), budget_remaining=c.get("budget_remaining"),
        min_payout=c.get("min_payout"), max_payout_per_video=c.get("max_payout_per_video"),
        platform_fee_pct=float(c.get("platform_fee_pct") or 0.0),
        ends_at=datetime.fromisoformat(ends) if isinstance(ends, str) and ends else ends,
        platforms=[p.lower() for p in c.get("platforms", [])], countries=[x.upper() for x in c.get("countries", [])],
        requirements=str(c.get("requirements", "")), footage_urls=list(c.get("footage_urls", [])),
        rights_note=str(c.get("rights_note", "")), submission_method=c.get("submission_method", "manual"),
        automation_allowed=c.get("automation_allowed"), raw=c,
    )


ADAPTERS: list[Adapter] = [WhopBountyAdapter(), FeedAdapter()]


def adapter_for(provider: str):
    return next((a for a in ADAPTERS if a.provider == provider), None)


# ----------------------------------------------------------------- upsert

_FIELDS = ["name", "creator", "url", "payout_model", "currency", "rate_per_1k", "flat_reward", "budget_total",
           "budget_remaining", "min_payout", "max_payout_per_video", "platform_fee_pct", "ends_at", "platforms",
           "countries", "requirements", "footage_urls", "rights_note", "submission_method", "automation_allowed", "raw"]


def upsert(s: Session, d: CampaignData) -> Campaign:
    c = s.execute(select(Campaign).where(Campaign.provider == d.provider,
                                         Campaign.external_id == d.external_id)).scalar_one_or_none()
    if c is None:
        c = Campaign(provider=d.provider, external_id=d.external_id, name=d.name)
        s.add(c)
    for f in _FIELDS:
        setattr(c, f, getattr(d, f))
    c.last_seen_at = now_utc()
    if d.status_hint not in ("open", "active", "") and c.status not in (CampaignStatus.active,):
        c.status, c.status_reason = CampaignStatus.ended, f"provider status: {d.status_hint}"
    s.flush()
    return c


# ------------------------------------------------------------- evaluation

def publishable_platforms(s: Session) -> set[str]:
    import vp_publishing

    out = set()
    for a in s.execute(select(SocialAccount).where(SocialAccount.publishing_allowed.is_(True))).scalars():
        ad = vp_publishing.get(a.platform)
        if ad and ad.availability(a).ok and a.health != "paused":
            out.add(a.platform)
    return out


def history_views(s: Session, platforms: list[str]) -> list[int]:
    latest = (select(MetricSnapshot.publication_id, func.max(MetricSnapshot.id).label("mid"))
              .group_by(MetricSnapshot.publication_id).subquery())
    q = (select(MetricSnapshot.views).join(latest, MetricSnapshot.id == latest.c.mid)
         .join(Publication, Publication.id == MetricSnapshot.publication_id))
    if platforms:
        q = q.where(Publication.platform.in_(platforms))
    return [int(v) for v in s.execute(q).scalars()]


def observed_rates(s: Session, provider: str) -> tuple[float | None, float | None]:
    rows = s.execute(select(CampaignSubmission.status).join(Campaign).where(Campaign.provider == provider)).scalars().all()
    resolved = [r for r in rows if r in (SubmissionStatus.approved, SubmissionStatus.rejected, SubmissionStatus.paid)]
    if len(resolved) < 5:
        return None, None
    approved = [r for r in resolved if r != SubmissionStatus.rejected]
    p_appr = len(approved) / len(resolved)
    paid = [r for r in approved if r == SubmissionStatus.paid]
    p_pay = (len(paid) / len(approved)) if len(approved) >= 5 else None
    return p_appr, p_pay


def measured_cost_per_clip(s: Session) -> float | None:
    from vp_shared.models import Clip, ClipStage

    n = s.execute(select(func.count(Clip.id)).where(Clip.stage != ClipStage.proposed)).scalar_one()
    if n < 5:
        return None
    total = s.execute(select(func.coalesce(func.sum(CostEntry.amount_usd), 0.0))
                      .where(CostEntry.status != CostEntryStatus.released)).scalar_one()
    return float(total) / n


def assess(s: Session, c: Campaign, *, publishable: set[str] | None = None, now: datetime | None = None) -> Campaign:
    now = now or now_utc()
    publishable = publishable if publishable is not None else publishable_platforms(s)
    country = os.environ.get("OPERATOR_COUNTRY", "").upper()

    def set_status(st: CampaignStatus, why: str):
        c.status, c.status_reason = st, why

    if c.status in (CampaignStatus.ended,):
        return c
    if c.ends_at and as_utc(c.ends_at) <= now:
        set_status(CampaignStatus.ended, "campaign end date has passed")
        return c
    floor = max(float(c.min_payout or 0.0), 1.0)
    if c.budget_remaining is not None and c.budget_remaining < floor:
        set_status(CampaignStatus.exhausted, f"remaining budget {c.budget_remaining} is below the payout floor")
        return c
    problems = []
    if c.payout_model == "cpm" and (c.rate_per_1k is None or c.rate_per_1k <= 0):
        problems.append("no per-1,000-views rate stated")
    if c.payout_model == "cpm" and (c.rate_per_1k or 0) > MAX_PLAUSIBLE_CPM:
        problems.append(f"implausible rate ${c.rate_per_1k}/1k views")
    if c.payout_model == "flat" and ((c.flat_reward or 0) <= 0 or (c.flat_reward or 0) > MAX_PLAUSIBLE_FLAT):
        problems.append(f"implausible flat reward {c.flat_reward}")
    if c.url and not c.url.startswith("https://"):
        problems.append("campaign link is not https")
    if not (c.requirements or "").strip():
        problems.append("no written requirements (brands may only reject on written rules)")
    if c.automation_allowed is False:
        problems.append("campaign forbids automated production")
    if problems:
        set_status(CampaignStatus.rejected, "suspicious or unusable: " + "; ".join(problems))
        return c
    if c.countries and country and country not in [x.upper() for x in c.countries]:
        set_status(CampaignStatus.rejected, f"not open to {country}")
        return c
    wanted = [p for p in (c.platforms or []) if p in SUPPORTED_PLATFORMS]
    if c.platforms and not wanted:
        set_status(CampaignStatus.rejected, f"only pays for platforms we can't publish to: {c.platforms}")
        return c

    p_appr, p_pay = observed_rates(s, c.provider)
    if c.payment_reliability is not None:
        p_pay = c.payment_reliability
    ev = profit.evaluate(
        payout_model=c.payout_model, rate_per_1k=c.rate_per_1k, flat_reward=c.flat_reward,
        min_payout=c.min_payout, max_payout_per_video=c.max_payout_per_video,
        budget_remaining=c.budget_remaining, fee_pct=c.platform_fee_pct,
        views=profit.view_model(history_views(s, wanted)), p_approval=p_appr, p_payment=p_pay,
        cost_per_clip=measured_cost_per_clip(s),
    )
    c.evaluation = ev.to_dict()
    if ev.expected_profit <= 0:
        set_status(CampaignStatus.rejected, f"unprofitable: expected ${ev.expected_profit:.2f} per clip (estimate)")
        return c
    blockers = []
    target = set(wanted) if wanted else SUPPORTED_PLATFORMS
    if not (target & publishable):
        blockers.append(f"no connected account allowed to publish to {sorted(target)}")
    if not c.footage_urls:
        blockers.append("no usable footage link yet (needs a direct media file or feed from the campaign)")
    if blockers:
        set_status(CampaignStatus.restricted, "; ".join(blockers))
        return c
    if c.status != CampaignStatus.active:
        set_status(CampaignStatus.eligible, f"expected profit ${ev.expected_profit:.2f}/clip (estimate)")
    return c


def rank(s: Session) -> list[Campaign]:
    cs = s.execute(select(Campaign).where(Campaign.status.in_([CampaignStatus.eligible, CampaignStatus.active])))
    return sorted(cs.scalars(), key=lambda c: -(c.evaluation or {}).get("expected_profit", 0.0))


def activate(s: Session, c: Campaign) -> int:
    """Register the campaign's footage as authorised sources so the normal
    acquisition pipeline picks it up. Returns the number of new sources."""
    new = 0
    for url in c.footage_urls or []:
        if not url.startswith("https://"):
            continue
        exists = s.execute(select(Source.id).where(Source.url == url, Source.campaign_id == c.id)).first()
        if exists:
            continue
        kind = SourceKind.direct_file if MEDIA_EXT.search(url) else SourceKind.rss
        s.add(Source(name=f"[campaign] {c.name}"[:200], kind=kind, url=url, campaign_id=c.id,
                     license_type=LicenseType.creator_authorized,
                     rights_evidence=f"Provided for clipping by campaign {c.provider}:{c.external_id} ({c.url})",
                     attribution=c.creator or c.name))
        new += 1
    c.status, c.status_reason = CampaignStatus.active, "producing clips"
    return new


# --------------------------------------------------------------- jobs

from vp_agents.stages import stage  # noqa: E402


@stage("discover.campaigns")
def discover_campaigns(s: Session, job) -> None:
    configured = [a for a in ADAPTERS if a.configured()]
    if not configured:
        raise_blocker(s, "campaigns.no_sources", "No campaign source connected",
                      "Connect Whop (WHOP_ACCESS_TOKEN) or add campaign feeds/manual campaigns. "
                      "Content Rewards and Vyro have no public API: add their campaigns manually.")
    else:
        resolve_blocker(s, "campaigns.no_sources")
    seen = 0
    for a in configured:
        for d in a.discover():
            upsert(s, d)
            seen += 1
    publishable = publishable_platforms(s)
    for c in s.execute(select(Campaign).where(Campaign.status.notin_([CampaignStatus.ended]))).scalars():
        before = c.status
        assess(s, c, publishable=publishable)
        if c.status != before:
            decide(s, AGENT, f"campaign_{c.status.value}", f"{c.name}: {c.status_reason}")
    top = rank(s)
    slots = int(os.environ.get("MAX_ACTIVE_CAMPAIGNS", "3"))
    for c in top[:slots]:
        if c.status == CampaignStatus.eligible:
            n = activate(s, c)
            decide(s, AGENT, "campaign_activated",
                   f"{c.name}: expected ${c.evaluation.get('expected_profit', 0):.2f}/clip (estimate), {n} footage source(s)")
    decide(s, AGENT, "campaigns_scanned", f"{seen} campaigns from {len(configured)} source(s); {len(top)} eligible/active")


@stage("submit.campaign")
def submit_campaign(s: Session, job) -> None:
    sub = s.get(CampaignSubmission, job.payload["submission_id"])
    if sub is None or sub.status not in (SubmissionStatus.ready,):
        return
    c = s.get(Campaign, sub.campaign_id)
    pub = s.get(Publication, sub.publication_id)
    if pub is None or pub.status != PublicationStatus.published or not pub.platform_url:
        sub.note = "waiting for a confirmed public post URL"
        return
    sub.post_url = pub.platform_url
    ad = adapter_for(c.provider)
    if c.submission_method != "api" or ad is None or not hasattr(ad, "submit") or not ad.configured():
        sub.status = SubmissionStatus.manual_required
        sub.note = "This campaign has no official submission API: submit the link from the dashboard."
        raise_blocker(s, "campaigns.manual_submissions", "Clip links waiting for manual campaign submission",
                      "See Campaigns → Submissions. Each needs one paste into the campaign page.")
        return
    res = ad.submit(c.external_id, pub.platform_url)
    sub.external_id = str(res.get("id", ""))
    sub.status, sub.submitted_at = SubmissionStatus.submitted, now_utc()
    enqueue(s, "poll.submission", f"poll:{sub.id}:{int(now_utc().timestamp() // 21600)}", {"submission_id": sub.id})
    decide(s, AGENT, "submitted", f"{c.name}: {pub.platform_url}")


def create_submission(s: Session, pub: Publication, campaign_id: int) -> None:
    exists = s.execute(select(CampaignSubmission.id).where(CampaignSubmission.campaign_id == campaign_id,
                                                           CampaignSubmission.publication_id == pub.id)).first()
    if exists:
        return
    sub = CampaignSubmission(campaign_id=campaign_id, publication_id=pub.id, post_url=pub.platform_url)
    s.add(sub)
    s.flush()
    enqueue(s, "submit.campaign", f"submit:{sub.id}", {"submission_id": sub.id})


WHOP_STATUS = {"submitted": SubmissionStatus.submitted, "in_progress": SubmissionStatus.submitted,
               "approved": SubmissionStatus.approved, "denied": SubmissionStatus.rejected}


@stage("poll.submission")
def poll_submission(s: Session, job) -> None:
    """Track approval and money for API-submitted clips. An approval creates a
    *pending* revenue entry with the provider's own reference; it becomes
    *confirmed* only when payout evidence is recorded."""
    sub = s.get(CampaignSubmission, job.payload["submission_id"])
    if sub is None or sub.status not in (SubmissionStatus.submitted, SubmissionStatus.approved):
        return
    c = s.get(Campaign, sub.campaign_id)
    ad = adapter_for(c.provider)
    if ad is None or not hasattr(ad, "submission_status") or not ad.configured():
        return
    res = ad.submission_status(sub.external_id)
    new = WHOP_STATUS.get(res.get("status") or "", sub.status)
    if new != sub.status:
        sub.status = new
        decide(s, AGENT, f"submission_{new.value}", f"{c.name}: {sub.post_url} {res.get('denial_reason') or ''}")
    if new == SubmissionStatus.approved and c.payout_model == "flat" and c.flat_reward:
        ref = f"{c.provider}:{sub.external_id}"
        if not s.execute(select(RevenueEntry.id).where(RevenueEntry.source == "whop_api",
                                                       RevenueEntry.external_ref == ref)).first():
            s.add(RevenueEntry(stream="campaign", source="whop_api", external_ref=ref, amount=float(c.flat_reward),
                               currency=c.currency, status=RevenueStatus.pending, campaign_id=c.id,
                               publication_id=sub.publication_id,
                               evidence=f"Whop bounty submission {sub.external_id} status=approved"))
        sub.resolved_at = now_utc()
    if new in (SubmissionStatus.submitted,):
        enqueue(s, "poll.submission", f"poll:{sub.id}:{int(now_utc().timestamp() // 21600)}",
                {"submission_id": sub.id}, run_after=now_utc() + _six_hours())


def _six_hours():
    from datetime import timedelta

    return timedelta(hours=6)
