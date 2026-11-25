"""qc.clip -> metadata.clip -> publication scheduling.

QC measures the rendered file. A failure a re-render can fix gets one more
render (bounded by ``QC_MAX_ATTEMPTS``); anything else discards the clip.
Metadata is written by Claude when a key is set and the budget allows, by
deterministic rules otherwise, and the non-optional rules (attribution,
paid-promotion disclosure) are applied either way. Clips are then scheduled
only onto accounts the owner allowed publishing to.
"""
from __future__ import annotations

import os
from datetime import timedelta

import vp_publishing
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from vp_shared import budget
from vp_shared.budget import BudgetExceeded
from vp_shared.events import decide
from vp_shared.jobs import StageBlocked, as_utc, enqueue, now_utc
from vp_shared.models import (
    Campaign,
    Clip,
    ClipStage,
    ContentItem,
    Job,
    Publication,
    PublicationStatus,
    SocialAccount,
    Source,
)
from vp_video import qc

from vp_agents import metadata as md

from . import stage

QC_AGENT = "Quality Control Specialist"
META_AGENT = "Copywriter"
SCHED_AGENT = "Social Media Manager"


def qc_max_attempts() -> int:
    return int(os.environ.get("QC_MAX_ATTEMPTS", "2"))


@stage("qc.clip")
def qc_clip(s: Session, job: Job) -> None:
    clip = s.get(Clip, job.payload["clip_id"])
    if clip is None or clip.stage != ClipStage.rendered:
        return
    words = len((clip.edit_plan or {}).get("words", []))
    report = qc.check(clip.render_path, caption_words=words, cover_path=clip.cover_path)
    clip.qc_attempts += 1
    clip.qc_report = report.to_dict()
    failed = ", ".join(f"{c.name} ({c.detail})" for c in report.failures)
    if report.passed:
        clip.stage = ClipStage.qc_passed
        decide(s, QC_AGENT, "qc_passed", f"clip {clip.id}: {len(report.checks)} checks passed",
               item_id=clip.item_id, clip_id=clip.id)
        enqueue(s, "metadata.clip", f"meta:{clip.id}", {"clip_id": clip.id})
        return
    if report.retryable and clip.qc_attempts < qc_max_attempts():
        clip.stage = ClipStage.proposed
        clip.render_path = ""
        enqueue(s, "edit.clip", f"edit:{clip.id}:qc{clip.qc_attempts}", {"clip_id": clip.id})
        decide(s, QC_AGENT, "qc_rerender", f"clip {clip.id} attempt {clip.qc_attempts}: {failed}",
               item_id=clip.item_id, clip_id=clip.id)
        return
    clip.stage = ClipStage.qc_failed
    decide(s, QC_AGENT, "qc_discarded", f"clip {clip.id}: {failed}", item_id=clip.item_id, clip_id=clip.id)


def _targets(s: Session, campaign: Campaign | None) -> list[SocialAccount]:
    out = []
    for a in s.execute(select(SocialAccount).where(SocialAccount.publishing_allowed.is_(True))
                       .order_by(SocialAccount.id)).scalars():
        if a.health == "paused":
            continue
        if campaign is not None and campaign.platforms and a.platform not in campaign.platforms:
            continue
        ad = vp_publishing.get(a.platform)
        if ad is None:
            continue
        out.append(a)
    return out


def _meta_input(s: Session, clip: Clip, item: ContentItem, campaign: Campaign | None,
                accounts: list[SocialAccount]) -> md.MetaInput:
    src = s.get(Source, item.source_id) if item.source_id else None
    first = accounts[0] if accounts else None
    return md.MetaInput(
        transcript=clip.transcript_text or "",
        source_title=item.title or "",
        attribution=(src.attribution if src else "") or "",
        license_type=item.license_type.value if item.license_type else "",
        campaign_name=campaign.name if campaign else "",
        campaign_creator=campaign.creator if campaign else "",
        campaign_requirements=campaign.requirements if campaign else "",
        platforms=sorted({a.platform for a in accounts}),
        niche=(first.niche if first else "") or "",
        handle=((first.brand or {}).get("handle", "") if first else ""),
    )


def write_metadata(s: Session, clip: Clip, mi: md.MetaInput, job_id: int | None = None) -> md.Metadata:
    meta: md.Metadata | None = None
    why_rules = "no ANTHROPIC_API_KEY set"
    if md.claude_available():
        est = md.estimate_usd(mi)
        try:
            entry = budget.reserve(s, category="llm.metadata", estimate_usd=est, item_id=clip.item_id,
                                   job_id=job_id, description=f"{md.model_name()} metadata for clip {clip.id}")
        except BudgetExceeded as e:
            entry, why_rules = None, f"budget: {e}"
        if entry is not None:
            try:
                meta = md.claude(mi)
                budget.commit(s, entry, meta.cost_usd)
            except md.MetadataError as e:
                budget.commit(s, entry, e.cost_usd)
                why_rules = f"model: {e}"
            except Exception as e:  # noqa: BLE001 - network/API error: may be billed, keep the estimate
                budget.commit(s, entry)
                why_rules = f"model call failed: {type(e).__name__}"
    if meta is None:
        meta = md.rules(mi)
        meta.notes.append(f"rules writer ({why_rules})")
    return md.enforce(meta, mi)


def _next_slot(s: Session, account: SocialAccount):
    gap = timedelta(hours=24 / max(account.max_posts_per_day, 1))
    last = s.execute(select(func.max(Publication.scheduled_for)).where(
        Publication.account_id == account.id,
        Publication.status.in_([PublicationStatus.scheduled, PublicationStatus.publishing,
                                PublicationStatus.published]))).scalar_one()
    now = now_utc()
    last = as_utc(last)
    return max(now, last + gap) if last else now


def schedule(s: Session, clip: Clip, accounts: list[SocialAccount]) -> list[Publication]:
    made = []
    for a in accounts:
        key = f"clip{clip.id}-acct{a.id}"
        if s.execute(select(Publication.id).where(Publication.idempotency_key == key)).first():
            continue
        pub = Publication(clip_id=clip.id, account_id=a.id, platform=a.platform, idempotency_key=key,
                          scheduled_for=_next_slot(s, a), campaign_id=clip.campaign_id)
        s.add(pub)
        s.flush()
        enqueue(s, "publish.publication", f"pub:{pub.id}", {"publication_id": pub.id}, run_after=pub.scheduled_for)
        decide(s, SCHED_AGENT, "scheduled", f"clip {clip.id} -> {a.platform} {a.display_name} at "
               f"{as_utc(pub.scheduled_for):%Y-%m-%d %H:%M} UTC", clip_id=clip.id)
        made.append(pub)
    return made


@stage("metadata.clip")
def metadata_clip(s: Session, job: Job) -> None:
    clip = s.get(Clip, job.payload["clip_id"])
    if clip is None or clip.stage not in (ClipStage.qc_passed, ClipStage.ready):
        return
    item = s.get(ContentItem, clip.item_id)
    campaign = s.get(Campaign, clip.campaign_id) if clip.campaign_id else None
    accounts = _targets(s, campaign)
    if clip.stage == ClipStage.qc_passed:
        meta = write_metadata(s, clip, _meta_input(s, clip, item, campaign, accounts), job.id)
        clip.title, clip.description, clip.hashtags = meta.title, meta.description, meta.hashtags
        clip.features = {**(clip.features or {}), "metadata": meta.to_dict()}
        clip.stage = ClipStage.ready
        decide(s, META_AGENT, "metadata_written", f"clip {clip.id} ({meta.writer}"
               f"{', ' + meta.model if meta.model else ''}, ${meta.cost_usd:.4f}): {meta.title}",
               item_id=clip.item_id, clip_id=clip.id)
    if not accounts:
        # The clip is finished; it waits here until an account is allowed to publish.
        # Commit first so the metadata (and its cost) survive the block.
        s.commit()
        raise StageBlocked("accounts.publishable", "No account is allowed to publish yet",
                           "Connect a YouTube or Facebook account and turn on publishing for it. "
                           "Finished clips are scheduled automatically once one is available.")
    schedule(s, clip, accounts)
