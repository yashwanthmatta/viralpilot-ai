"""ViralPilot API: monitoring data + the few settings the owner configures once.

Every number returned comes from the database; nothing is estimated or
invented here. Fields with no data source yet (e.g. revenue) return null.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Literal

import vp_publishing
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl, field_validator
from sqlalchemy import func, select
from vp_agents import rights
from vp_shared import budget, db, jobs
from vp_shared.config import get_settings
from vp_shared.events import autopilot, decide, set_autopilot
from vp_shared.models import (
    AgentDecision,
    AuditLog,
    Campaign,
    CampaignStatus,
    CampaignSubmission,
    Clip,
    ClipStage,
    ContentItem,
    CostEntry,
    CostEntryStatus,
    IntegrationBlocker,
    ItemStage,
    Job,
    JobStatus,
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

from vp_api.security import (
    check_rate_limit,
    clear_session,
    client_ip,
    issue_session,
    require_session,
    verify_password,
)

PLATFORMS = ("youtube", "tiktok", "instagram", "facebook")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.create_all()  # no-op when Alembic migrations already created the schema
    yield


app = FastAPI(title="ViralPilot API", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().web_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["content-type", "x-vp-csrf"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    return resp


def audit(s, request: Request, action: str, detail: str = "") -> None:
    s.add(AuditLog(action=action, detail=detail[:2000], ip=client_ip(request)))


def _count(s, model, *where) -> int:
    return int(s.execute(select(func.count()).select_from(model).where(*where)).scalar_one())


def _iso(dt):
    return dt.isoformat() if dt else None


# ------------------------------------------------------------------ public

@app.get("/healthz")
def healthz() -> dict:
    with db.session_scope() as s:
        s.execute(select(1))
        st = autopilot(s)
        last = jobs.as_utc(st.last_tick_at)
    stale = last is None or (jobs.now_utc() - last).total_seconds() > 5 * get_settings().supervisor_interval_s
    return {"ok": True, "supervisor_heartbeat": _iso(last), "supervisor_stale": stale}


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    ip = client_ip(request)
    check_rate_limit(ip)
    ok = verify_password(body.password)
    with db.session_scope() as s:
        audit(s, request, "login_ok" if ok else "login_failed")
    if not ok:
        raise HTTPException(401, "wrong password")
    issue_session(response)
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(response: Response) -> dict:
    clear_session(response)
    return {"ok": True}


# --------------------------------------------------------------- protected

auth = [Depends(require_session)]


@app.get("/api/me", dependencies=auth)
def me() -> dict:
    return {"user": "owner"}


def _revenue_status(s) -> dict:
    from vp_analytics import finance
    o = finance.overview(s)
    active = _count(s, Campaign, Campaign.status == CampaignStatus.active)
    return {"confirmed_today": o["confirmed_today"], "confirmed_month": o["confirmed_month"],
            "pending": o["pending"], "net_month_confirmed": o["net_month_confirmed"],
            "progress_to_100k": o["progress_to_100k"], "next_milestone": o["next_milestone"],
            "active_campaigns": active}


@app.get("/api/status", dependencies=auth)
def status_snapshot() -> dict:
    with db.session_scope() as s:
        st = autopilot(s)
        spend = budget.summary(s)
        b = budget.get_budget(s)
        latest = (
            select(MetricSnapshot.publication_id, func.max(MetricSnapshot.id).label("mid"))
            .group_by(MetricSnapshot.publication_id).subquery()
        )
        views = s.execute(
            select(func.coalesce(func.sum(MetricSnapshot.views), 0)).join(latest, MetricSnapshot.id == latest.c.mid)
        ).scalar_one()
        last = jobs.as_utc(st.last_tick_at)
        return {
            "autopilot": {
                "enabled": st.enabled, "reason": st.reason, "changed_at": _iso(st.changed_at),
                "last_tick_at": _iso(last),
                "supervisor_stale": last is None
                or (jobs.now_utc() - last).total_seconds() > 5 * get_settings().supervisor_interval_s,
            },
            "counts": {
                "discovered": _count(s, ContentItem),
                "rights_rejected": _count(s, ContentItem, ContentItem.stage == ItemStage.rights_rejected),
                "imported": _count(s, ContentItem, ContentItem.stage.in_(
                    [ItemStage.imported, ItemStage.transcribed, ItemStage.clipped, ItemStage.done])),
                "analyzed": _count(s, ContentItem, ContentItem.stage.in_(
                    [ItemStage.transcribed, ItemStage.clipped, ItemStage.done])),
                "clips": _count(s, Clip),
                "editing": _count(s, Clip, Clip.stage == ClipStage.proposed),
                "scheduled": _count(s, Publication, Publication.status == PublicationStatus.scheduled),
                "published": _count(s, Publication, Publication.status == PublicationStatus.published),
                "publish_blocked": _count(s, Publication, Publication.status == PublicationStatus.blocked),
                "total_views": int(views or 0),
                "jobs_pending": _count(s, Job, Job.status == JobStatus.pending),
                "jobs_running": _count(s, Job, Job.status == JobStatus.running),
                "jobs_blocked": _count(s, Job, Job.status == JobStatus.blocked),
                "jobs_failed": _count(s, Job, Job.status == JobStatus.failed),
                "errors_auto_recovered": _count(s, AgentDecision, AgentDecision.action.in_(
                    ["recovered_jobs", "job_retry_scheduled"])),
            },
            "spend": {
                "today": round(spend.today, 4), "daily_limit": spend.daily_limit,
                "month": round(spend.month, 4), "monthly_limit": spend.monthly_limit,
                "per_video_limit": b.per_item_limit_usd, "max_videos_per_day": b.max_videos_per_day,
                "total": round(spend.total, 4), "total_limit": spend.total_limit,
            },
            # Verified ledger only: confirmed and pending are kept apart, nothing is estimated here.
            "revenue": _revenue_status(s),
            "blockers": [
                {"key": x.key, "title": x.title, "detail": x.detail, "since": _iso(x.first_seen_at)}
                for x in s.execute(select(IntegrationBlocker).where(IntegrationBlocker.resolved.is_(False))
                                   .order_by(IntegrationBlocker.first_seen_at)).scalars()
            ],
            "upcoming": [
                {"id": p.id, "platform": p.platform, "clip_id": p.clip_id, "at": _iso(p.scheduled_for)}
                for p in s.execute(select(Publication).where(Publication.status == PublicationStatus.scheduled)
                                   .order_by(Publication.scheduled_for).limit(20)).scalars()
            ],
        }


@app.get("/api/decisions", dependencies=auth)
def decisions(limit: int = 50, agent: str | None = None) -> list[dict]:
    with db.session_scope() as s:
        q = select(AgentDecision).order_by(AgentDecision.id.desc()).limit(max(1, min(limit, 500)))
        if agent:
            q = q.where(AgentDecision.agent == agent)
        return [{"id": d.id, "at": _iso(d.created_at), "agent": d.agent, "action": d.action, "detail": d.detail,
                 "item_id": d.item_id, "clip_id": d.clip_id} for d in s.execute(q).scalars()]


@app.get("/api/agents", dependencies=auth)
def agents() -> list[dict]:
    with db.session_scope() as s:
        rows = s.execute(select(AgentDecision.agent, func.count(), func.max(AgentDecision.created_at))
                         .group_by(AgentDecision.agent)).all()
        return [{"agent": a, "decisions": n, "last_active": _iso(t)} for a, n, t in rows]


@app.get("/api/content", dependencies=auth)
def content(limit: int = 100) -> list[dict]:
    with db.session_scope() as s:
        q = select(ContentItem).order_by(ContentItem.id.desc()).limit(max(1, min(limit, 500)))
        return [{"id": i.id, "title": i.title, "stage": i.stage.value, "license": i.license_type.value,
                 "rights_note": i.rights_note, "source_id": i.source_id, "discovered_at": _iso(i.discovered_at)}
                for i in s.execute(q).scalars()]


@app.get("/api/clips", dependencies=auth)
def clips(limit: int = 100) -> list[dict]:
    with db.session_scope() as s:
        q = select(Clip).order_by(Clip.id.desc()).limit(max(1, min(limit, 500)))
        return [{"id": c.id, "item_id": c.item_id, "start_s": c.start_s, "end_s": c.end_s, "score": c.score,
                 "stage": c.stage.value, "title": c.title, "reason": c.reason, "qc": c.qc_report,
                 "qc_attempts": c.qc_attempts, "description": c.description, "hashtags": c.hashtags,
                 "metadata": (c.features or {}).get("metadata"), "campaign_id": c.campaign_id,
                 "duration_s": c.duration_s, "has_render": bool(c.render_path),
                 "has_cover": bool(c.cover_path)} for c in s.execute(q).scalars()]


def _media_file(path: str) -> str:
    """Only files inside MEDIA_DIR are ever served."""
    root = os.path.realpath(get_settings().media_dir)
    real = os.path.realpath(path or "")
    if not path or os.path.commonpath([root, real]) != root or not os.path.isfile(real):
        raise HTTPException(404, "file not available")
    return real


@app.get("/api/clips/{clip_id}/{kind}", dependencies=auth)
def clip_file(clip_id: int, kind: Literal["video", "cover"]) -> FileResponse:
    with db.session_scope() as s:
        c = s.get(Clip, clip_id)
        if c is None:
            raise HTTPException(404, "clip not found")
        path = c.render_path if kind == "video" else c.cover_path
    real = _media_file(path)
    return FileResponse(real, media_type="video/mp4" if kind == "video" else "image/jpeg",
                        headers={"Cache-Control": "private, max-age=300"})


@app.get("/api/publications", dependencies=auth)
def publications(limit: int = 100) -> list[dict]:
    with db.session_scope() as s:
        q = select(Publication).order_by(Publication.id.desc()).limit(max(1, min(limit, 500)))
        return [{"id": p.id, "clip_id": p.clip_id, "platform": p.platform, "status": p.status.value,
                 "scheduled_for": _iso(p.scheduled_for), "confirmed_at": _iso(p.confirmed_at),
                 "platform_post_id": p.platform_post_id, "url": p.platform_url, "error": p.error}
                for p in s.execute(q).scalars()]


@app.get("/api/costs", dependencies=auth)
def costs(limit: int = 200) -> dict:
    with db.session_scope() as s:
        by_cat = s.execute(select(CostEntry.category, func.sum(CostEntry.amount_usd))
                           .where(CostEntry.status != CostEntryStatus.released)
                           .group_by(CostEntry.category)).all()
        q = select(CostEntry).order_by(CostEntry.id.desc()).limit(max(1, min(limit, 1000)))
        return {
            "by_category": {c: round(float(v or 0), 4) for c, v in by_cat},
            "entries": [{"id": e.id, "at": _iso(e.created_at), "category": e.category, "usd": e.amount_usd,
                         "status": e.status.value, "description": e.description, "item_id": e.item_id}
                        for e in s.execute(q).scalars()],
        }


@app.get("/api/jobs", dependencies=auth)
def list_jobs(status: JobStatus | None = None, limit: int = 100) -> list[dict]:
    with db.session_scope() as s:
        q = select(Job).order_by(Job.id.desc()).limit(max(1, min(limit, 500)))
        if status:
            q = q.where(Job.status == status)
        return [{"id": j.id, "kind": j.kind, "status": j.status.value, "attempts": j.attempts,
                 "max_attempts": j.max_attempts, "run_after": _iso(j.run_after), "last_error": j.last_error[:1000],
                 "created_at": _iso(j.created_at)} for j in s.execute(q).scalars()]


@app.post("/api/jobs/{job_id}/retry", dependencies=auth)
def retry_job(job_id: int, request: Request) -> dict:
    """Optional: requeue a dead-lettered job (the system never needs this to keep running)."""
    with db.session_scope() as s:
        j = s.get(Job, job_id)
        if j is None or j.status not in (JobStatus.failed, JobStatus.blocked):
            raise HTTPException(400, "only failed or blocked jobs can be retried")
        j.status, j.attempts, j.run_after = JobStatus.pending, 0, jobs.now_utc()
        audit(s, request, "job_retry", f"job {job_id}")
    return {"ok": True}


@app.get("/api/audit", dependencies=auth)
def audit_log(limit: int = 100) -> list[dict]:
    with db.session_scope() as s:
        q = select(AuditLog).order_by(AuditLog.id.desc()).limit(max(1, min(limit, 500)))
        return [{"at": _iso(a.created_at), "action": a.action, "detail": a.detail, "ip": a.ip}
                for a in s.execute(q).scalars()]


# ---------------------------------------------------------- the two buttons

@app.post("/api/autopilot/start", dependencies=auth)
def start(request: Request) -> dict:
    with db.session_scope() as s:
        from vp_agents.campaigns import ADAPTERS

        has_campaigns = _count(s, Campaign) > 0 or any(a.configured() for a in ADAPTERS)
        if _count(s, Source, Source.enabled.is_(True)) == 0 and not has_campaigns:
            raise HTTPException(400, "Add an authorised source or a paid campaign before starting autopilot.")
        set_autopilot(s, True, "started from dashboard")
        audit(s, request, "autopilot_start")
    return {"enabled": True}


@app.post("/api/autopilot/stop", dependencies=auth)
def stop(request: Request) -> dict:
    """Emergency stop: workers stop picking up jobs at once (each job checks
    before it starts). Nothing is deleted; START resumes where it left off."""
    with db.session_scope() as s:
        set_autopilot(s, False, "emergency stop from dashboard")
        audit(s, request, "autopilot_stop")
    return {"enabled": False}


# ----------------------------------------------------------------- sources

class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    kind: Literal["rss"] = "rss"
    license_type: LicenseType
    rights_evidence: str = Field(min_length=1, max_length=4000)
    attribution: str = Field(default="", max_length=500)
    niche: str = Field(default="", max_length=80)

    @field_validator("url")
    @classmethod
    def https_only(cls, v: HttpUrl) -> HttpUrl:
        if v.scheme != "https":
            raise ValueError("source URL must use https")
        return v


@app.get("/api/sources", dependencies=auth)
def list_sources() -> list[dict]:
    with db.session_scope() as s:
        return [{"id": x.id, "name": x.name, "kind": x.kind.value, "url": x.url, "license": x.license_type.value,
                 "rights_evidence": x.rights_evidence, "attribution": x.attribution, "niche": x.niche,
                 "enabled": x.enabled, "last_polled_at": _iso(x.last_polled_at)}
                for x in s.execute(select(Source).order_by(Source.id)).scalars()]


@app.post("/api/sources", dependencies=auth, status_code=201)
def add_source(body: SourceIn, request: Request) -> dict:
    decision = rights.evaluate(body.license_type, body.rights_evidence, body.attribution)
    if not decision.allowed:
        raise HTTPException(400, f"Source rejected: {decision.reason}")
    with db.session_scope() as s:
        src = Source(name=body.name, url=str(body.url), kind=SourceKind(body.kind), license_type=body.license_type,
                     rights_evidence=body.rights_evidence, attribution=body.attribution, niche=body.niche)
        s.add(src)
        s.flush()
        decide(s, "Content Acquisition Specialist", "source_authorised", f"{body.name} ({body.license_type.value})")
        audit(s, request, "source_added", f"{src.id} {body.name}")
        return {"id": src.id}


@app.post("/api/sources/{source_id}/toggle", dependencies=auth)
def toggle_source(source_id: int, request: Request) -> dict:
    with db.session_scope() as s:
        src = s.get(Source, source_id)
        if src is None:
            raise HTTPException(404)
        src.enabled = not src.enabled
        audit(s, request, "source_toggled", f"{source_id} -> {src.enabled}")
        return {"enabled": src.enabled}


# ---------------------------------------------------------------- accounts

class AccountIn(BaseModel):
    platform: Literal["youtube", "tiktok", "instagram", "facebook"]
    display_name: str = Field(default="", max_length=200)
    max_posts_per_day: int = Field(default=1, ge=0, le=20)
    publishing_allowed: bool = False


class AccountPatch(BaseModel):
    max_posts_per_day: int | None = Field(default=None, ge=0, le=20)
    publishing_allowed: bool | None = None


@app.get("/api/accounts", dependencies=auth)
def list_accounts() -> list[dict]:
    with db.session_scope() as s:
        out = []
        for a in s.execute(select(SocialAccount).order_by(SocialAccount.id)).scalars():
            adapter = vp_publishing.get(a.platform)
            av = adapter.availability(a) if adapter else None
            out.append({"id": a.id, "platform": a.platform, "name": a.display_name,
                        "connected": bool(a.encrypted_credentials),
                        "publishing_allowed": a.publishing_allowed, "max_posts_per_day": a.max_posts_per_day,
                        "can_publish": bool(av and av.ok), "blocked_reason": av.reason if av and not av.ok else ""})
        return out


@app.post("/api/accounts", dependencies=auth, status_code=201)
def add_account(body: AccountIn, request: Request) -> dict:
    with db.session_scope() as s:
        a = SocialAccount(platform=body.platform, display_name=body.display_name,
                          max_posts_per_day=body.max_posts_per_day, publishing_allowed=body.publishing_allowed)
        s.add(a)
        s.flush()
        audit(s, request, "account_added", f"{a.id} {body.platform}")
        return {"id": a.id}


@app.patch("/api/accounts/{account_id}", dependencies=auth)
def patch_account(account_id: int, body: AccountPatch, request: Request) -> dict:
    with db.session_scope() as s:
        a = s.get(SocialAccount, account_id)
        if a is None:
            raise HTTPException(404)
        if body.max_posts_per_day is not None:
            a.max_posts_per_day = body.max_posts_per_day
        if body.publishing_allowed is not None:
            a.publishing_allowed = body.publishing_allowed
        audit(s, request, "account_changed", f"{account_id}: {body.model_dump(exclude_none=True)}")
        return {"ok": True}


# ------------------------------------------------------------------ budget

class BudgetIn(BaseModel):
    daily_limit_usd: float = Field(ge=0, le=1000)
    monthly_limit_usd: float = Field(ge=0, le=20000)
    per_item_limit_usd: float = Field(ge=0, le=100)
    max_videos_per_day: int = Field(ge=0, le=50)
    total_limit_usd: float = Field(default=100.0, ge=0, le=1_000_000)
    max_videos_ceiling: int = Field(default=5, ge=0, le=200)


@app.get("/api/budget", dependencies=auth)
def get_budget() -> dict:
    with db.session_scope() as s:
        b = budget.get_budget(s)
        return {"daily_limit_usd": b.daily_limit_usd, "monthly_limit_usd": b.monthly_limit_usd,
                "per_item_limit_usd": b.per_item_limit_usd, "max_videos_per_day": b.max_videos_per_day,
                "total_limit_usd": b.total_limit_usd, "max_videos_ceiling": b.max_videos_ceiling}


@app.put("/api/budget", dependencies=auth)
def put_budget(body: BudgetIn, request: Request) -> dict:
    with db.session_scope() as s:
        b = budget.get_budget(s, lock=True)
        b.daily_limit_usd, b.monthly_limit_usd = body.daily_limit_usd, body.monthly_limit_usd
        b.per_item_limit_usd, b.max_videos_per_day = body.per_item_limit_usd, body.max_videos_per_day
        b.total_limit_usd, b.max_videos_ceiling = body.total_limit_usd, max(body.max_videos_ceiling, body.max_videos_per_day)
        decide(s, "Cost Optimization Specialist", "limits_changed", str(body.model_dump()))
        audit(s, request, "budget_changed", str(body.model_dump()))
    return body.model_dump()


@app.get("/api/platforms", dependencies=auth)
def platforms() -> list[dict]:
    """What each platform integration can do today, stated plainly."""
    out = []
    for p in PLATFORMS:
        adapter = vp_publishing.get(p)
        av = adapter.availability(SocialAccount(platform=p)) if adapter else None
        out.append({"platform": p, "available": bool(av and av.ok), "reason": av.reason if av else "no adapter"})
    return out


# --------------------------------------------------------------- campaigns

class CampaignIn(BaseModel):
    """Manual entry for marketplaces without an API (Content Rewards, Vyro) and direct deals."""

    provider: Literal["content_rewards", "vyro", "direct", "whop_manual", "other"]
    external_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=300)
    creator: str = Field(default="", max_length=200)
    url: HttpUrl
    payout_model: Literal["cpm", "flat"] = "cpm"
    rate_per_1k: float | None = Field(default=None, ge=0, le=100)
    flat_reward: float | None = Field(default=None, ge=0, le=100000)
    budget_total: float | None = Field(default=None, ge=0)
    budget_remaining: float | None = Field(default=None, ge=0)
    min_payout: float | None = Field(default=None, ge=0)
    max_payout_per_video: float | None = Field(default=None, ge=0)
    platform_fee_pct: float = Field(default=0.0, ge=0, le=1)
    ends_at: str | None = None
    platforms: list[Literal["youtube", "facebook", "instagram", "tiktok", "x", "other"]] = []
    countries: list[str] = []
    requirements: str = Field(min_length=1, max_length=20000)
    footage_urls: list[HttpUrl] = []
    rights_note: str = Field(default="", max_length=2000)


def _campaign_row(c: Campaign, subs: dict | None = None) -> dict:
    return {"id": c.id, "provider": c.provider, "external_id": c.external_id, "name": c.name, "creator": c.creator,
            "url": c.url, "payout_model": c.payout_model, "rate_per_1k": c.rate_per_1k, "flat_reward": c.flat_reward,
            "budget_total": c.budget_total, "budget_remaining": c.budget_remaining, "min_payout": c.min_payout,
            "max_payout_per_video": c.max_payout_per_video, "platform_fee_pct": c.platform_fee_pct,
            "ends_at": _iso(c.ends_at), "platforms": c.platforms, "countries": c.countries,
            "requirements": c.requirements, "footage_urls": c.footage_urls, "submission_method": c.submission_method,
            "status": c.status.value, "status_reason": c.status_reason, "evaluation": c.evaluation,
            "submissions": (subs or {}).get(c.id, {}), "last_seen_at": _iso(c.last_seen_at)}


@app.get("/api/campaigns", dependencies=auth)
def list_campaigns() -> list[dict]:
    with db.session_scope() as s:
        subs: dict = {}
        for cid, st, n in s.execute(select(CampaignSubmission.campaign_id, CampaignSubmission.status, func.count())
                                    .group_by(CampaignSubmission.campaign_id, CampaignSubmission.status)).all():
            subs.setdefault(cid, {})[st.value] = n
        rows = s.execute(select(Campaign)).scalars().all()
        rows.sort(key=lambda c: (c.status not in (CampaignStatus.active, CampaignStatus.eligible),
                                 -(c.evaluation or {}).get("expected_profit", -1e9)))
        return [_campaign_row(c, subs) for c in rows]


@app.post("/api/campaigns", dependencies=auth, status_code=201)
def add_campaign(body: CampaignIn, request: Request) -> dict:
    from datetime import datetime

    from vp_agents import campaigns as cmp

    data = body.model_dump()
    data["url"] = str(body.url)
    data["footage_urls"] = [str(u) for u in body.footage_urls]
    try:
        data["ends_at"] = datetime.fromisoformat(body.ends_at) if body.ends_at else None
    except ValueError as e:
        raise HTTPException(422, "ends_at must be ISO 8601") from e
    data["submission_method"] = "manual"
    with db.session_scope() as s:
        c = cmp.upsert(s, cmp.from_dict(data))
        cmp.assess(s, c)
        audit(s, request, "campaign_added", f"{c.id} {c.provider}:{c.external_id}")
        decide(s, "Campaign Strategist", f"campaign_{c.status.value}", f"{c.name}: {c.status_reason}")
        return _campaign_row(c)


@app.post("/api/campaigns/{campaign_id}/{action}", dependencies=auth)
def campaign_action(campaign_id: int, action: Literal["pause", "reassess"], request: Request) -> dict:
    from vp_agents import campaigns as cmp

    with db.session_scope() as s:
        c = s.get(Campaign, campaign_id)
        if c is None:
            raise HTTPException(404)
        if action == "pause":
            c.status, c.status_reason = CampaignStatus.restricted, "paused by owner"
        else:
            c.status = CampaignStatus.discovered
            cmp.assess(s, c)
        audit(s, request, f"campaign_{action}", str(campaign_id))
        return _campaign_row(c)


@app.get("/api/submissions", dependencies=auth)
def list_submissions(limit: int = 200) -> list[dict]:
    with db.session_scope() as s:
        q = (select(CampaignSubmission, Campaign).join(Campaign).order_by(CampaignSubmission.id.desc())
             .limit(max(1, min(limit, 500))))
        return [{"id": x.id, "campaign": c.name, "campaign_url": c.url, "provider": c.provider,
                 "status": x.status.value, "post_url": x.post_url, "qualified_views": x.qualified_views,
                 "note": x.note, "submitted_at": _iso(x.submitted_at)} for x, c in s.execute(q).all()]


class SubmissionUpdate(BaseModel):
    status: Literal["submitted", "approved", "rejected"]
    note: str = Field(default="", max_length=1000)


@app.post("/api/submissions/{sub_id}", dependencies=auth)
def update_submission(sub_id: int, body: SubmissionUpdate, request: Request) -> dict:
    """For campaigns without an API: record that you pasted the link, or the outcome."""
    with db.session_scope() as s:
        x = s.get(CampaignSubmission, sub_id)
        if x is None:
            raise HTTPException(404)
        x.status = SubmissionStatus(body.status)
        x.note = body.note or x.note
        if body.status == "submitted":
            x.submitted_at = jobs.now_utc()
        else:
            x.resolved_at = jobs.now_utc()
        audit(s, request, "submission_updated", f"{sub_id} -> {body.status}")
        return {"ok": True}


# ----------------------------------------------------------------- revenue

class RevenueIn(BaseModel):
    stream: Literal["campaign", "youtube", "facebook", "instagram", "tiktok", "affiliate", "direct", "other"]
    amount: float = Field(gt=0, le=1_000_000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    status: Literal["pending", "confirmed"]
    evidence: str = Field(min_length=6, max_length=2000, description="payout ID, statement reference, invoice no.")
    external_ref: str = Field(min_length=1, max_length=200)
    occurred_at: str | None = None
    campaign_id: int | None = None
    publication_id: int | None = None
    account_id: int | None = None


@app.get("/api/revenue", dependencies=auth)
def list_revenue(limit: int = 300) -> list[dict]:
    with db.session_scope() as s:
        q = select(RevenueEntry).order_by(RevenueEntry.occurred_at.desc()).limit(max(1, min(limit, 1000)))
        return [{"id": r.id, "stream": r.stream, "source": r.source, "amount": r.amount, "currency": r.currency,
                 "status": r.status.value, "evidence": r.evidence, "occurred_at": _iso(r.occurred_at),
                 "campaign_id": r.campaign_id, "publication_id": r.publication_id} for r in s.execute(q).scalars()]


@app.post("/api/revenue", dependencies=auth, status_code=201)
def add_revenue(body: RevenueIn, request: Request) -> dict:
    """Record money the system can't read from an API (e.g. a Content Rewards
    payout). Evidence is required; the entry is marked as owner-entered."""
    from datetime import datetime

    with db.session_scope() as s:
        exists = s.execute(select(RevenueEntry.id).where(RevenueEntry.source == "owner_entry",
                                                         RevenueEntry.external_ref == body.external_ref)).first()
        if exists:
            raise HTTPException(409, "an entry with this reference already exists")
        r = RevenueEntry(stream=body.stream, source="owner_entry", external_ref=body.external_ref, amount=body.amount,
                         currency=body.currency.upper(), status=RevenueStatus(body.status), evidence=body.evidence,
                         occurred_at=datetime.fromisoformat(body.occurred_at) if body.occurred_at else jobs.now_utc(),
                         campaign_id=body.campaign_id, publication_id=body.publication_id, account_id=body.account_id)
        s.add(r)
        s.flush()
        audit(s, request, "revenue_recorded", f"{r.id} {body.status} {body.amount} {body.currency}")
        return {"id": r.id}


class ConfirmIn(BaseModel):
    evidence: str = Field(min_length=6, max_length=2000)


@app.post("/api/revenue/{rev_id}/confirm", dependencies=auth)
def confirm_revenue(rev_id: int, body: ConfirmIn, request: Request) -> dict:
    with db.session_scope() as s:
        r = s.get(RevenueEntry, rev_id)
        if r is None or r.status != RevenueStatus.pending:
            raise HTTPException(400, "only pending entries can be confirmed")
        r.status = RevenueStatus.confirmed
        r.evidence = f"{r.evidence} | confirmed: {body.evidence}"
        audit(s, request, "revenue_confirmed", f"{rev_id}: {body.evidence}")
        return {"ok": True}


@app.get("/api/finance", dependencies=auth)
def finance_overview() -> dict:
    from vp_analytics import finance

    with db.session_scope() as s:
        return {"overview": finance.overview(s), "breakdown": finance.by_dimension(s),
                "milestones": finance.milestone_plan(s), "last_14d": finance.last_14d(s)}
