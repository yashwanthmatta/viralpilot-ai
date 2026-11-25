"""Agent 2, Content Acquisition Specialist.

Phase 1 supports RSS / Atom feeds (podcasts, video feeds, Internet Archive
collections, a creator's own feed). For each entry it:

1. works out the licence (entry licence tag, then the source's declared
   licence) and runs the rights gate; unclear rights => rejected;
2. de-duplicates on (source, entry id) and later on the file's SHA-256;
3. downloads the media with a hard size cap, then queues transcription.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

import defusedxml.ElementTree as ET
from sqlalchemy import select
from sqlalchemy.orm import Session
from vp_shared import netsafety
from vp_shared.config import get_settings
from vp_shared.events import decide
from vp_shared.jobs import RetryLater, enqueue, now_utc
from vp_shared.models import ContentItem, ItemStage, Job, LicenseType, Source, SourceKind

from vp_agents import rights

from . import stage

AGENT = "Content Acquisition Specialist"
MEDIA_TYPES = ("video/", "audio/")


@dataclass
class FeedEntry:
    guid: str
    title: str
    media_url: str
    media_type: str
    license_url: str


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_feed(xml_bytes: bytes) -> list[FeedEntry]:
    """Parse RSS 2.0 or Atom without network access to external entities."""
    root = ET.fromstring(xml_bytes)  # defusedxml: no entity expansion or external fetches
    entries: list[FeedEntry] = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        guid = title = media_url = media_type = license_url = ""
        for child in node:
            name = _local(child.tag)
            if name in ("guid", "id"):
                guid = (child.text or "").strip()
            elif name == "title":
                title = (child.text or "").strip()
            elif name == "enclosure" or (name == "content" and child.get("url")):
                media_url = child.get("url", "")
                media_type = child.get("type", "")
            elif name == "link" and child.get("rel") == "enclosure":
                media_url = child.get("href", "")
                media_type = child.get("type", "")
            elif name == "link" and child.get("rel") == "license":
                license_url = child.get("href", "")
            elif name in ("license", "rights"):
                license_url = (child.text or child.get("href") or "").strip()
        if media_url:
            entries.append(FeedEntry(guid or media_url, title, media_url, media_type, license_url))
    return entries


def fingerprint(source_id: int, guid: str) -> str:
    return hashlib.sha256(f"{source_id}:{guid}".encode()).hexdigest()


def ingest_entries(s: Session, src: Source, entries: list[FeedEntry]) -> dict[str, int]:
    counts = {"new": 0, "duplicate": 0, "rejected": 0}
    for e in entries:
        fp = fingerprint(src.id, e.guid)
        if s.execute(select(ContentItem.id).where(ContentItem.fingerprint == fp)).first():
            counts["duplicate"] += 1
            continue
        lic = rights.license_from_url(e.license_url) if e.license_url else src.license_type
        evidence = e.license_url or src.rights_evidence
        decision = rights.evaluate(lic, evidence, src.attribution)
        if e.media_type and not e.media_type.startswith(MEDIA_TYPES):
            decision = rights.RightsDecision(False, lic, f"not audio/video ({e.media_type})")
        item = ContentItem(
            source_id=src.id,
            fingerprint=fp,
            external_id=e.guid[:500],
            title=e.title[:500],
            media_url=e.media_url[:2000],
            license_type=decision.license_type,
            rights_note=decision.reason,
            stage=ItemStage.discovered if decision.allowed else ItemStage.rights_rejected,
            meta={"media_type": e.media_type, "license_url": e.license_url},
        )
        s.add(item)
        s.flush()
        if decision.allowed:
            counts["new"] += 1
            enqueue(s, "import.item", f"import:{item.id}", {"item_id": item.id})
            decide(s, AGENT, "accepted_source_item", f"{e.title!r}: {decision.reason}", item_id=item.id)
        else:
            counts["rejected"] += 1
            decide(s, AGENT, "rejected_rights", f"{e.title!r}: {decision.reason}", item_id=item.id)
    return counts


def fetch(url: str, timeout: float = 30.0):
    return netsafety.safe_get(url, timeout=timeout)


@stage("discover.source")
def discover_source(s: Session, job: Job) -> None:
    src = s.get(Source, job.payload["source_id"])
    if src is None or not src.enabled:
        return
    if src.kind != SourceKind.rss:
        # Other source kinds arrive in later phases; never guess at them.
        decide(s, AGENT, "skipped_source", f"source kind {src.kind.value} not supported yet")
        return
    resp = fetch(src.url)
    if resp.status_code == 429:
        raise RetryLater("feed rate-limited", int(resp.headers.get("Retry-After", "600")))
    resp.raise_for_status()
    counts = ingest_entries(s, src, parse_feed(resp.content))
    src.last_polled_at = now_utc()
    decide(s, "Trend Researcher", "polled_source", f"{src.name}: {counts}")


@stage("import.item")
def import_item(s: Session, job: Job) -> None:
    item = s.get(ContentItem, job.payload["item_id"])
    if item is None or item.stage != ItemStage.discovered:
        return  # already imported or rejected: idempotent no-op
    if item.license_type not in rights.ALLOWED:  # belt and braces
        item.stage = ItemStage.rights_rejected
        return
    cfg = get_settings()
    os.makedirs(cfg.media_dir, exist_ok=True)
    tmp = os.path.join(cfg.media_dir, f"item-{item.id}.part")
    h = hashlib.sha256()
    size = 0
    with netsafety.safe_stream(item.media_url) as r:
        if r.status_code == 429:
            raise RetryLater("media host rate-limited", int(r.headers.get("Retry-After", "900")))
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                size += len(chunk)
                if size > cfg.max_import_bytes:
                    f.close()
                    os.remove(tmp)
                    item.stage = ItemStage.discarded
                    decide(s, AGENT, "discarded_too_large", f"{item.title!r} > {cfg.max_import_bytes} bytes", item_id=item.id)
                    return
                h.update(chunk)
                f.write(chunk)
    digest = h.hexdigest()
    dup = s.execute(
        select(ContentItem.id).where(ContentItem.content_sha256 == digest, ContentItem.id != item.id)
    ).first()
    if dup:
        os.remove(tmp)
        item.stage = ItemStage.discarded
        decide(s, AGENT, "discarded_duplicate", f"same file as item {dup[0]}", item_id=item.id)
        return
    final = os.path.join(cfg.media_dir, f"item-{item.id}")
    os.replace(tmp, final)
    item.local_path, item.content_sha256, item.stage = final, digest, ItemStage.imported
    item.meta = {**item.meta, "bytes": size}
    enqueue(s, "transcribe.item", f"transcribe:{item.id}", {"item_id": item.id})
    decide(s, AGENT, "imported", f"{item.title!r} ({size} bytes)", item_id=item.id)


__all__ = ["parse_feed", "ingest_entries", "fingerprint", "LicenseType"]
