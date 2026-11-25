"""Agent 7, Social Media Manager: publisher adapters.

Contract every adapter must follow:

* ``availability(account)`` says honestly whether this account can be
  published to right now, and if not, why (audit pending, missing scope...).
* ``publish(...)`` returns a ``Confirmation`` carrying the platform's own
  post id. If the platform did not return one, the adapter must raise.
  The publishing stage refuses to mark anything published without it.
* ``lookup(...)`` finds a post made by an earlier, interrupted attempt
  (via the idempotency key embedded in the post), so a crash between
  "platform accepted" and "we saved the result" never causes a double post.
  Adapters that can't look up return ``NotImplemented``; the stage then
  refuses to retry automatically rather than risk a duplicate.
"""
from __future__ import annotations

from dataclasses import dataclass

from vp_shared.models import Clip, Publication, SocialAccount


@dataclass(frozen=True)
class Availability:
    ok: bool
    blocker_key: str = ""
    reason: str = ""


@dataclass(frozen=True)
class Confirmation:
    platform_post_id: str
    url: str = ""


class PublishUnconfirmed(Exception):
    """The platform call returned without a post id."""


class PlatformBusy(Exception):
    """Quota or rate limit: try again later. Nothing was posted."""

    def __init__(self, msg: str, retry_s: int = 3600):
        super().__init__(msg)
        self.retry_s = retry_s


class AccountNeedsReconnect(Exception):
    """The owner revoked access or the token expired."""


class Publisher:
    platform = "base"
    oauth = False  # True when the dashboard can start an OAuth connect for this platform

    def platform_status(self) -> Availability:
        """Platform-level answer (no specific account)."""
        return self.availability(SocialAccount(platform=self.platform))

    def availability(self, account: SocialAccount) -> Availability:
        raise NotImplementedError

    def publish(self, account: SocialAccount, clip: Clip, pub: Publication) -> Confirmation:
        raise NotImplementedError

    def lookup(self, account: SocialAccount, pub: Publication):
        return NotImplemented

    def stats(self, account: SocialAccount, post_ids: list[str]):
        """{post_id: {"views": int, "likes": int, "comments": int}} or NotImplemented."""
        return NotImplemented


class _NotYetApproved(Publisher):
    """Adapters for platforms whose publishing access needs an approval
    we don't have yet. They never attempt to post."""

    reason = ""

    def availability(self, account: SocialAccount) -> Availability:
        return Availability(False, f"platform.{self.platform}", self.reason)


class TikTokPublisher(_NotYetApproved):
    platform = "tiktok"
    reason = (
        "TikTok Content Posting API (Direct Post) requires an approved app audit; unaudited apps "
        "can only post privately. TikTok's posting guidelines also require creator-facing consent "
        "and privacy choices, which may rule out fully unattended posting."
    )


class InstagramPublisher(_NotYetApproved):
    platform = "instagram"
    reason = (
        "Instagram Reels publishing needs a Business/Creator account linked to a Facebook Page and "
        "Meta App Review approval for content publishing permissions. Posts are capped per 24 hours."
    )


from .facebook import FacebookPublisher  # noqa: E402
from .youtube import YouTubePublisher  # noqa: E402

REGISTRY: dict[str, Publisher] = {
    p.platform: p for p in (YouTubePublisher(), TikTokPublisher(), InstagramPublisher(), FacebookPublisher())
}


def get(platform: str) -> Publisher | None:
    return REGISTRY.get(platform)
