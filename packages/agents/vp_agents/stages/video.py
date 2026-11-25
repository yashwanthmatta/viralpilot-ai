"""Agents 3 and 4: Viral Clip Specialist and Professional Video Editor.

transcribe.item -> clip.item -> edit.clip -> qc.clip (phase 3)

All three are local compute (no paid API), deterministic, and idempotent:
each checks the current stage before doing work, so a retried job is safe.
"""
from __future__ import annotations

import os
import tempfile
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from vp_shared import budget
from vp_shared.config import get_settings
from vp_shared.events import decide
from vp_shared.jobs import RetryLater, StageBlocked, enqueue, now_utc
from vp_shared.models import Clip, ClipStage, ContentItem, ItemStage, Job, TranscriptCache
from vp_video import clipfinder, editplan, ffmpeg, render, transcribe

from . import stage

CLIPPER = "Viral Clip Specialist"
EDITOR = "Professional Video Editor"


def load_transcript(s: Session, item: ContentItem) -> transcribe.Transcript | None:
    row = s.execute(select(TranscriptCache).where(TranscriptCache.content_sha256 == item.content_sha256)).scalar_one_or_none()
    return transcribe.Transcript.from_dict(row.data) if row else None


@stage("transcribe.item")
def transcribe_item(s: Session, job: Job) -> None:
    item = s.get(ContentItem, job.payload["item_id"])
    if item is None or item.stage != ItemStage.imported:
        return
    cached = load_transcript(s, item)
    if cached is None:
        info = ffmpeg.probe(item.local_path)
        if not info.has_audio:
            item.stage = ItemStage.discarded
            decide(s, CLIPPER, "discarded_no_audio", item.title, item_id=item.id)
            return
        tr = transcribe.get_transcriber()
        with tempfile.TemporaryDirectory() as td:
            wav = ffmpeg.extract_audio(item.local_path, os.path.join(td, "a.wav"))
            try:
                result = tr.transcribe(wav)
            except transcribe.TranscriberUnavailable as e:
                raise StageBlocked("worker.transcriber", "Transcription model unavailable on the worker", str(e)) from e
        s.add(TranscriptCache(content_sha256=item.content_sha256, model=tr.name, language=result.language,
                              data=result.to_dict()))
        n_words = len(result.words())
        decide(s, CLIPPER, "transcribed", f"{item.title!r}: {n_words} words, {result.duration:.0f}s ({tr.name})",
               item_id=item.id)
    else:
        decide(s, CLIPPER, "transcript_cache_hit", item.title, item_id=item.id)
    item.stage = ItemStage.transcribed
    enqueue(s, "clip.item", f"clip:{item.id}", {"item_id": item.id})


@stage("clip.item")
def clip_item(s: Session, job: Job) -> None:
    item = s.get(ContentItem, job.payload["item_id"])
    if item is None or item.stage != ItemStage.transcribed:
        return
    tr = load_transcript(s, item)
    if tr is None:
        raise RuntimeError("transcript missing from cache")
    max_clips = int(os.environ.get("MAX_CLIPS_PER_SOURCE", "3"))
    cands = clipfinder.find_clips(tr, max_clips=max_clips)
    if not cands:
        item.stage = ItemStage.discarded
        decide(s, CLIPPER, "no_strong_moments", f"{item.title!r}: no candidate passed the minimum score",
               item_id=item.id)
        return
    for c in cands:
        clip = Clip(item_id=item.id, campaign_id=item.campaign_id, start_s=c.start, end_s=c.end, score=c.score, reason=c.reason,
                    features=c.features, transcript_text=c.text[:8000])
        s.add(clip)
        s.flush()
        # Campaign clips (paid) go to the front of the editing queue.
        delay = timedelta(0) if item.campaign_id else timedelta(minutes=30)
        enqueue(s, "edit.clip", f"edit:{clip.id}", {"clip_id": clip.id}, run_after=now_utc() + delay)
        decide(s, CLIPPER, "clip_selected",
               f"{c.start:.1f}-{c.end:.1f}s score {c.score:.2f} ({c.reason})", item_id=item.id, clip_id=clip.id)
    item.stage = ItemStage.clipped


@stage("edit.clip")
def edit_clip(s: Session, job: Job) -> None:
    clip = s.get(Clip, job.payload["clip_id"])
    if clip is None or clip.stage != ClipStage.proposed:
        return
    cap = budget.get_budget(s).max_videos_per_day
    done_today = s.execute(select(func.count(Clip.id)).where(
        Clip.stage != ClipStage.proposed, Clip.created_at >= now_utc() - timedelta(hours=24),
        Clip.render_path != "")).scalar_one()
    if done_today >= cap:
        raise RetryLater(f"daily video cap reached ({cap}/day)", 3600)
    item = s.get(ContentItem, clip.item_id)
    tr = load_transcript(s, item)
    if tr is None:
        raise RuntimeError("transcript missing from cache")
    plan = editplan.plan(tr.words(), clip.start_s, clip.end_s)
    out_dir = os.path.join(get_settings().media_dir, "renders")
    res = render.render(item.local_path, plan, out_dir, f"clip-{clip.id}")
    clip.edit_plan = plan.to_dict()
    clip.render_path, clip.cover_path, clip.duration_s = res.video_path, res.cover_path, res.duration
    clip.stage = ClipStage.rendered
    enqueue(s, "qc.clip", f"qc:{clip.id}", {"clip_id": clip.id})
    decide(s, EDITOR, "rendered",
           f"clip {clip.id}: {res.width}x{res.height}, {res.duration:.1f}s, removed {plan.removed_s:.1f}s of pauses, "
           f"{len(plan.pieces)} cuts", item_id=item.id, clip_id=clip.id)
