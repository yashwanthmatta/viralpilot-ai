"""Database schema.

The database is the single source of truth. Redis only carries job ids to
wake workers up; if Redis is wiped, the supervisor re-dispatches every job
that is still pending in the database, so nothing is lost on restart.
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vp_shared.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- autopilot

class AutopilotState(Base):
    """Singleton row (id=1). The START / STOP AUTOPILOT buttons flip `enabled`."""

    __tablename__ = "autopilot_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reason: Mapped[str] = mapped_column(String(500), default="never started")
    last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_discovery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BudgetSettings(Base):
    """Singleton row (id=1) with the hard spending ceilings."""

    __tablename__ = "budget_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    daily_limit_usd: Mapped[float] = mapped_column(Float)
    monthly_limit_usd: Mapped[float] = mapped_column(Float)
    # Per-video ceiling: a single item may not consume more than this.
    per_item_limit_usd: Mapped[float] = mapped_column(Float, default=0.50)
    max_videos_per_day: Mapped[int] = mapped_column(Integer, default=3)


class CostEntryStatus(str, enum.Enum):
    reserved = "reserved"
    committed = "committed"
    released = "released"


class CostEntry(Base):
    """Every paid step reserves its estimated cost *before* running, then
    commits the actual cost (or releases the reservation on failure)."""

    __tablename__ = "cost_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    category: Mapped[str] = mapped_column(String(40))  # llm, transcription, render, storage, tts, api
    description: Mapped[str] = mapped_column(String(300), default="")
    amount_usd: Mapped[float] = mapped_column(Float)
    status: Mapped[CostEntryStatus] = mapped_column(Enum(CostEntryStatus), default=CostEntryStatus.reserved)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("content_items.id"), nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


# ------------------------------------------------------------------ sources

class LicenseType(str, enum.Enum):
    user_owned = "user_owned"              # the account owner made it
    creator_authorized = "creator_authorized"  # written permission from the creator
    cc_by = "cc_by"                        # Creative Commons Attribution (commercial reuse OK, credit required)
    cc_by_sa = "cc_by_sa"
    cc0 = "cc0"
    public_domain = "public_domain"
    licensed_library = "licensed_library"  # stock library under a paid / commercial licence
    unknown = "unknown"


class SourceKind(str, enum.Enum):
    rss = "rss"                  # podcast / video RSS or Atom feed
    youtube_own_channel = "youtube_own_channel"
    stock_library = "stock_library"
    manual_library = "manual_library"  # a storage bucket the user owns


class Source(Base):
    """A content source the user has explicitly authorised."""

    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[SourceKind] = mapped_column(Enum(SourceKind))
    url: Mapped[str] = mapped_column(String(1000))
    license_type: Mapped[LicenseType] = mapped_column(Enum(LicenseType), default=LicenseType.unknown)
    # Where the proof of rights lives: licence URL, permission letter id, etc.
    rights_evidence: Mapped[str] = mapped_column(Text, default="")
    attribution: Mapped[str] = mapped_column(String(500), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    niche: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# -------------------------------------------------------------- pipeline

class ItemStage(str, enum.Enum):
    discovered = "discovered"
    rights_rejected = "rights_rejected"
    imported = "imported"
    transcribed = "transcribed"
    clipped = "clipped"
    discarded = "discarded"
    done = "done"


class ContentItem(Base):
    """One source video/episode. `fingerprint` prevents processing twice."""

    __tablename__ = "content_items"
    __table_args__ = (UniqueConstraint("fingerprint", name="uq_item_fingerprint"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(128))
    external_id: Mapped[str] = mapped_column(String(500), default="")
    title: Mapped[str] = mapped_column(String(500), default="")
    media_url: Mapped[str] = mapped_column(String(2000), default="")
    local_path: Mapped[str] = mapped_column(String(1000), default="")
    content_sha256: Mapped[str] = mapped_column(String(64), default="", index=True)
    license_type: Mapped[LicenseType] = mapped_column(Enum(LicenseType), default=LicenseType.unknown)
    rights_note: Mapped[str] = mapped_column(Text, default="")
    stage: Mapped[ItemStage] = mapped_column(Enum(ItemStage), default=ItemStage.discovered, index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[Source | None] = relationship()


class ClipStage(str, enum.Enum):
    proposed = "proposed"
    rendered = "rendered"
    qc_failed = "qc_failed"
    qc_passed = "qc_passed"
    ready = "ready"         # metadata written, waiting for a publish slot
    discarded = "discarded"


class Clip(Base):
    __tablename__ = "clips"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("content_items.id"), index=True)
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text, default="")
    stage: Mapped[ClipStage] = mapped_column(Enum(ClipStage), default=ClipStage.proposed, index=True)
    render_path: Mapped[str] = mapped_column(String(1000), default="")
    qc_attempts: Mapped[int] = mapped_column(Integer, default=0)
    qc_report: Mapped[dict] = mapped_column(JSON, default=dict)
    title: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    item: Mapped[ContentItem] = relationship()


class PublicationStatus(str, enum.Enum):
    scheduled = "scheduled"
    publishing = "publishing"
    published = "published"   # ONLY set when the platform returned a post id
    failed = "failed"
    blocked = "blocked"       # platform not permitted / not approved
    cancelled = "cancelled"


class Publication(Base):
    """One clip on one platform. The unique constraint plus `idempotency_key`
    make it impossible to publish the same clip to the same account twice."""

    __tablename__ = "publications"
    __table_args__ = (UniqueConstraint("clip_id", "account_id", name="uq_pub_clip_account"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    clip_id: Mapped[int] = mapped_column(ForeignKey("clips.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("social_accounts.id"))
    platform: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[PublicationStatus] = mapped_column(Enum(PublicationStatus), default=PublicationStatus.scheduled)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    platform_post_id: Mapped[str] = mapped_column(String(200), default="")
    platform_url: Mapped[str] = mapped_column(String(1000), default="")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class SocialAccount(Base):
    __tablename__ = "social_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(40))  # youtube, tiktok, instagram, facebook
    display_name: Mapped[str] = mapped_column(String(200), default="")
    external_account_id: Mapped[str] = mapped_column(String(200), default="")
    encrypted_credentials: Mapped[str] = mapped_column(Text, default="")
    publishing_allowed: Mapped[bool] = mapped_column(Boolean, default=False)  # user permission switch
    max_posts_per_day: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    avg_view_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)


# -------------------------------------------------------------------- jobs

class JobStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"        # exhausted retries (dead letter)
    blocked = "blocked"      # cannot run until a human fixes something external
    cancelled = "cancelled"


class Job(Base):
    """Durable job record. `dedupe_key` makes enqueueing idempotent."""

    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(60), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.pending, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ----------------------------------------------------------- observability

class AgentDecision(Base):
    """Human-readable log of what each agent decided and why (dashboard feed)."""

    __tablename__ = "agent_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    agent: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[str] = mapped_column(Text, default="")
    item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clip_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class IntegrationBlocker(Base):
    """Something outside the system's control (API audit, missing credential,
    unbuilt stage). `key` is unique so the same blocker isn't logged twice."""

    __tablename__ = "integration_blockers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(120), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text, default="")
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Security-relevant actions: logins, autopilot on/off, setting changes."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(100), default="admin")
    action: Mapped[str] = mapped_column(String(100))
    detail: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
