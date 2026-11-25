"""Publishing stage: idempotent, confirmation-only.

A Publication becomes ``published`` only when the platform returned its own
post id. Blocked platforms are marked blocked and skipped; other platforms
carry on.
"""
from __future__ import annotations

from datetime import timedelta

import vp_publishing
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from vp_shared.events import decide, raise_blocker, resolve_blocker
from vp_shared.jobs import RetryLater, StageBlocked, as_utc, enqueue, now_utc
from vp_shared.models import Clip, Job, MetricSnapshot, Publication, PublicationStatus, SocialAccount

from . import stage

AGENT = "Social Media Manager"
ANALYST = "Performance Analyst"
METRIC_CHECKS = [("1h", timedelta(hours=1)), ("24h", timedelta(hours=24)), ("72h", timedelta(hours=72)),
                 ("7d", timedelta(days=7)), ("30d", timedelta(days=30))]


def _published_today(s: Session, account_id: int) -> int:
    since = now_utc() - timedelta(hours=24)
    return int(
        s.execute(
            select(func.count(Publication.id)).where(
                Publication.account_id == account_id,
                Publication.status == PublicationStatus.published,
                Publication.confirmed_at >= since,
            )
        ).scalar_one()
    )


def _mark_published(s: Session, pub: Publication, conf: vp_publishing.Confirmation) -> None:
    if not conf or not (conf.platform_post_id or "").strip():
        raise vp_publishing.PublishUnconfirmed("platform returned no post id")
    pub.status = PublicationStatus.published
    pub.platform_post_id = conf.platform_post_id
    pub.platform_url = conf.url
    pub.confirmed_at = now_utc()
    pub.error = ""
    decide(s, AGENT, "published", f"{pub.platform} post {conf.platform_post_id}", clip_id=pub.clip_id)
    for label, delay in METRIC_CHECKS:
        enqueue(s, "analytics.publication", f"metrics:{pub.id}:{label}", {"publication_id": pub.id},
                run_after=now_utc() + delay)
    if pub.campaign_id:
        from vp_agents.campaigns import create_submission

        create_submission(s, pub, pub.campaign_id)


@stage("publish.publication")
def publish_publication(s: Session, job: Job) -> None:
    pub = s.get(Publication, job.payload["publication_id"])
    if pub is None or pub.status in (
        PublicationStatus.published, PublicationStatus.cancelled, PublicationStatus.blocked
    ):
        return
    account = s.get(SocialAccount, pub.account_id)
    clip = s.get(Clip, pub.clip_id)
    adapter = vp_publishing.get(pub.platform)

    if account is None or adapter is None:
        pub.status, pub.error = PublicationStatus.failed, "unknown account or platform"
        return
    if not account.publishing_allowed:
        pub.status, pub.error = PublicationStatus.blocked, "publishing not permitted for this account in settings"
        decide(s, AGENT, "skipped_not_permitted", account.display_name, clip_id=pub.clip_id)
        return

    avail = adapter.availability(account)
    if not avail.ok:
        # Nothing was attempted. The publication keeps its place and the job
        # re-checks by itself, so fixing the cause (approval, reconnect) is enough.
        pub.error = avail.reason
        decide(s, AGENT, "platform_blocked", avail.reason, clip_id=pub.clip_id)
        s.commit()
        raise StageBlocked(avail.blocker_key, f"{pub.platform}: publishing blocked", avail.reason)
    resolve_blocker(s, f"platform.{pub.platform}")

    if as_utc(pub.scheduled_for) > now_utc():
        raise RetryLater("not yet scheduled time", 300)

    # A previous attempt may have reached the platform and then crashed.
    if pub.status == PublicationStatus.publishing:
        found = adapter.lookup(account, pub)
        if found is NotImplemented:
            pub.status = PublicationStatus.failed
            pub.error = ("previous attempt was interrupted and this platform can't be checked for an "
                         "existing post; not retrying to avoid a duplicate")
            raise_blocker(s, f"pub.unknown.{pub.id}", "A publish attempt needs a manual check", pub.error)
            return
        if found is not None:
            _mark_published(s, pub, found)
            return

    if _published_today(s, account.id) >= account.max_posts_per_day:
        raise RetryLater("daily posting limit for this account reached", 3600)

    pub.status = PublicationStatus.publishing
    pub.attempts += 1
    s.commit()  # persist "publishing" BEFORE calling the platform (crash safety)

    try:
        conf = adapter.publish(account, clip, pub)
        _mark_published(s, pub, conf)
    except vp_publishing.PlatformBusy as e:
        # Quota/rate limit: the next attempt still goes through lookup() first.
        pub.error = str(e)
        decide(s, AGENT, "platform_busy", str(e), clip_id=pub.clip_id)
        s.commit()
        raise RetryLater(str(e), e.retry_s) from e
    except vp_publishing.AccountNeedsReconnect as e:
        pub.error = str(e)
        account.health, account.health_note = "paused", f"reconnect needed: {e}"
        decide(s, AGENT, "account_needs_reconnect", str(e), clip_id=pub.clip_id)
        s.commit()
        raise StageBlocked(f"account.{account.id}.connect", f"{account.display_name}: reconnect needed", str(e)) from e
    except vp_publishing.PublishUnconfirmed as e:
        pub.status, pub.error = PublicationStatus.failed, str(e)
        decide(s, AGENT, "publish_unconfirmed", str(e), clip_id=pub.clip_id)
    except Exception as e:
        # Network error etc: we don't know if it landed. Leave status
        # "publishing" so the retry goes through lookup() first.
        pub.error = f"{type(e).__name__}: {e}"
        raise


@stage("analytics.publication")
def collect_metrics(s: Session, job: Job) -> None:
    """Real platform numbers only. If an adapter can't report metrics, nothing is recorded."""
    pub = s.get(Publication, job.payload["publication_id"])
    if pub is None or pub.status != PublicationStatus.published or not pub.platform_post_id:
        return
    account = s.get(SocialAccount, pub.account_id)
    adapter = vp_publishing.get(pub.platform)
    if account is None or adapter is None:
        return
    try:
        stats = adapter.stats(account, [pub.platform_post_id])
    except vp_publishing.PlatformBusy as e:
        raise RetryLater(str(e), e.retry_s) from e
    if stats is NotImplemented:
        decide(s, ANALYST, "metrics_unavailable", f"{pub.platform} adapter has no metrics API", clip_id=pub.clip_id)
        return
    st = stats.get(pub.platform_post_id)
    if st is None:
        decide(s, ANALYST, "post_missing", f"{pub.platform} post {pub.platform_post_id} not returned "
               "(deleted or private?)", clip_id=pub.clip_id)
        return
    s.add(MetricSnapshot(publication_id=pub.id, views=st.get("views", 0), likes=st.get("likes", 0),
                         comments=st.get("comments", 0), shares=st.get("shares", 0)))
    decide(s, ANALYST, "metrics", f"{pub.platform} {pub.platform_post_id}: {st.get('views', 0)} views",
           clip_id=pub.clip_id)
