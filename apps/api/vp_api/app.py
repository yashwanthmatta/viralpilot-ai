"""ViralPilot API: monitoring data + the few settings the owner configures once.

Every number returned comes from the database; nothing is estimated or
invented here. Fields with no data source yet (e.g. revenue) return null.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal

import vp_publishing
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl, field_validator
from sqlalchemy import func, select
from vp_agents import rights
from vp_shared import budget, db, jobs
from vp_shared.config import get_settings
from vp_shared.events import autopilot, decide, set_autopilot
from vp_shared.models import (
    AgentDecision,
    AuditLog,
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
    SocialAccount,
    Source,
    SourceKind,
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
            },
            "revenue": None,  # no revenue API integrated yet: shown as unavailable, never estimated
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
                 "has_render": bool(c.render_path)} for c in s.execute(q).scalars()]


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
        if _count(s, Source, Source.enabled.is_(True)) == 0:
            raise HTTPException(400, "Add at least one authorised source before starting autopilot.")
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


@app.get("/api/budget", dependencies=auth)
def get_budget() -> dict:
    with db.session_scope() as s:
        b = budget.get_budget(s)
        return {"daily_limit_usd": b.daily_limit_usd, "monthly_limit_usd": b.monthly_limit_usd,
                "per_item_limit_usd": b.per_item_limit_usd, "max_videos_per_day": b.max_videos_per_day}


@app.put("/api/budget", dependencies=auth)
def put_budget(body: BudgetIn, request: Request) -> dict:
    with db.session_scope() as s:
        b = budget.get_budget(s, lock=True)
        b.daily_limit_usd, b.monthly_limit_usd = body.daily_limit_usd, body.monthly_limit_usd
        b.per_item_limit_usd, b.max_videos_per_day = body.per_item_limit_usd, body.max_videos_per_day
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
