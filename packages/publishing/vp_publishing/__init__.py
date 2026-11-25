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


class Publisher:
    platform = "base"

    def availability(self, account: SocialAccount) -> Availability:
        raise NotImplementedError

    def publish(self, account: SocialAccount, clip: Clip, pub: Publication) -> Confirmation:
        raise NotImplementedError

    def lookup(self, account: SocialAccount, pub: Publication):
        return NotImplemented


class _NotYetApproved(Publisher):
    """Adapters for platforms whose publishing access needs an approval
    we don't have yet. They never attempt to post."""

    reason = ""

    def availability(self, account: SocialAccount) -> Availability:
        return Availability(False, f"platform.{self.platform}", self.reason)


class YouTubePublisher(_NotYetApproved):
    platform = "youtube"
    reason = (
        "YouTube upload adapter ships in phase 5 (OAuth + videos.insert). Note: uploads from an "
        "unaudited Google API project are locked to private until the project passes YouTube's "
        "API compliance audit, and the default quota allows only a handful of uploads a day."
    )


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


class FacebookPublisher(_NotYetApproved):
    platform = "facebook"
    reason = (
        "Facebook Reels publishing to a Page needs Meta App Review approval for Page publishing "
        "permissions."
    )


REGISTRY: dict[str, Publisher] = {
    p.platform: p for p in (YouTubePublisher(), TikTokPublisher(), InstagramPublisher(), FacebookPublisher())
}


def get(platform: str) -> Publisher | None:
    return REGISTRY.get(platform)
