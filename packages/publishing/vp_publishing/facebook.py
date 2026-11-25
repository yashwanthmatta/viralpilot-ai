"""Facebook Reels publishing to a Page through the official Graph API.

Flow (Meta's Reels Publishing API):
  1. ``POST /{page-id}/video_reels upload_phase=start`` -> ``video_id``
  2. ``POST rupload.facebook.com/video-upload/{ver}/{video_id}`` with the file
  3. ``POST /{page-id}/video_reels upload_phase=finish video_state=PUBLISHED``
  4. ``GET /{video_id}?fields=status`` until ``publish_status == published``

The publication is confirmed only at step 4. The ``video_id`` is saved
after step 1 and the step reached after each later step, so an interrupted
attempt is checked instead of posting again.

Needs a Meta app with Facebook Login and the permissions
``pages_show_list``, ``pages_read_engagement``, ``pages_manage_posts`` (and
``read_insights`` for metrics), which require Meta App Review for use by
anyone who isn't an admin/developer/tester of the app.
"""
from __future__ import annotations

import os
import time
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import object_session
from vp_shared import crypto
from vp_shared.models import Clip, Publication, SocialAccount

from . import AccountNeedsReconnect, Availability, Confirmation, PlatformBusy, Publisher, PublishUnconfirmed

GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v26.0")
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
RUPLOAD = f"https://rupload.facebook.com/video-upload/{GRAPH_VERSION}"
DIALOG = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"
SCOPES = ["pages_show_list", "pages_read_engagement", "pages_manage_posts", "read_insights"]
MAX_PER_PAGE_24H = 30  # Meta's documented limit for API-published reels per Page
CONFIRM_WAIT_S = float(os.environ.get("FB_CONFIRM_WAIT_S", "60"))


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def configured() -> bool:
    return bool(_env("META_APP_ID") and _env("META_APP_SECRET") and _env("PUBLIC_API_URL"))


def redirect_uri() -> str:
    return _env("PUBLIC_API_URL").rstrip("/") + "/api/oauth/facebook/callback"


def auth_url(state: str) -> str:
    return DIALOG + "?" + urlencode({"client_id": _env("META_APP_ID"), "redirect_uri": redirect_uri(),
                                     "state": state, "scope": ",".join(SCOPES), "response_type": "code"})


_http: httpx.Client | None = None


def set_http(client: httpx.Client | None) -> None:
    global _http
    _http = client


def http() -> httpx.Client:
    global _http
    if _http is None:
        _http = httpx.Client(timeout=httpx.Timeout(60.0, write=900.0), follow_redirects=False)
    return _http


def _check(r: httpx.Response, what: str) -> dict:
    if r.status_code >= 400:
        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {"message": r.text[:300]}
        code, sub = err.get("code"), err.get("error_subcode")
        msg = err.get("message", "")
        if code == 190:  # expired / revoked token
            raise AccountNeedsReconnect(f"Facebook access expired or was revoked ({msg})")
        if code in (4, 17, 32, 613) or "limit" in msg.lower():
            raise PlatformBusy(f"Facebook {what}: rate limit ({msg})", 3 * 3600)
        raise httpx.HTTPStatusError(f"Facebook {what} failed ({r.status_code}, code {code}/{sub}): {msg}",
                                    request=r.request, response=r)
    return r.json() if r.content else {}


def exchange_code(code: str) -> str:
    """Code -> long-lived user token (Page tokens derived from it don't expire)."""
    short = _check(http().get(f"{GRAPH}/oauth/access_token", params={
        "client_id": _env("META_APP_ID"), "client_secret": _env("META_APP_SECRET"),
        "redirect_uri": redirect_uri(), "code": code}), "token exchange")["access_token"]
    long = _check(http().get(f"{GRAPH}/oauth/access_token", params={
        "grant_type": "fb_exchange_token", "client_id": _env("META_APP_ID"),
        "client_secret": _env("META_APP_SECRET"), "fb_exchange_token": short}), "long-lived token")
    return long["access_token"]


def pages(user_token: str) -> list[dict]:
    """Pages where this user may create content."""
    data = _check(http().get(f"{GRAPH}/me/accounts", params={
        "fields": "id,name,access_token,tasks", "limit": 100, "access_token": user_token}), "me/accounts")
    return [p for p in data.get("data", []) if "CREATE_CONTENT" in (p.get("tasks") or [])]


class FacebookPublisher(Publisher):
    platform = "facebook"
    oauth = True

    def platform_status(self) -> Availability:
        if not configured():
            return Availability(False, "platform.facebook", "Meta app is not configured (META_APP_ID, META_APP_SECRET, "
                                                            "PUBLIC_API_URL). Publishing for other people's Pages also "
                                                            "needs Meta App Review.")
        return Availability(True, reason="Official Reels Publishing API is set up. Connect a Page and allow "
                                         "publishing. Until Meta App Review approves the app, only Pages of "
                                         "app admins/testers can be used.")

    def availability(self, account: SocialAccount) -> Availability:
        if not configured():
            return self.platform_status()
        if not account.encrypted_credentials:
            return Availability(False, f"account.{account.id}.connect",
                                "Page not connected yet: use Connect Facebook on the Social accounts page.")
        try:
            crypto.decrypt(account.encrypted_credentials)
        except Exception:  # noqa: BLE001
            return Availability(False, f"account.{account.id}.connect",
                                "Stored Facebook credentials can't be decrypted; connect the Page again.")
        if account.health == "paused" and "reconnect" in (account.health_note or ""):
            return Availability(False, f"account.{account.id}.connect", account.health_note)
        return Availability(True)

    def _token(self, account: SocialAccount) -> str:
        return crypto.decrypt(account.encrypted_credentials)["page_token"]

    def _save(self, pub: Publication, **state) -> None:
        pub.platform_state = {**(pub.platform_state or {}), **state}
        sess = object_session(pub)
        if sess is not None:
            sess.commit()  # survive a crash between steps

    def _status(self, video_id: str, token: str) -> dict:
        return _check(http().get(f"{GRAPH}/{video_id}", params={"fields": "status", "access_token": token}),
                      "status").get("status", {})

    def _confirm(self, video_id: str, token: str, wait_s: float) -> Confirmation | None:
        deadline = time.monotonic() + wait_s
        while True:
            st = self._status(video_id, token)
            pub_status = (st.get("publishing_phase") or {}).get("publish_status")
            if pub_status == "published":
                return Confirmation(video_id, f"https://www.facebook.com/reel/{video_id}")
            if st.get("video_status") in ("error", "upload_failed", "expired") or pub_status == "error":
                raise PublishUnconfirmed(f"Facebook rejected the reel: {st}")
            if time.monotonic() >= deadline:
                return None
            time.sleep(5)

    def publish(self, account: SocialAccount, clip: Clip, pub: Publication) -> Confirmation:
        token = self._token(account)
        page = account.external_account_id
        state = pub.platform_state or {}
        vid = state.get("video_id")
        if not vid or state.get("step") == "started":
            start = _check(http().post(f"{GRAPH}/{page}/video_reels",
                                       json={"upload_phase": "start", "access_token": token}), "start")
            vid = str(start.get("video_id") or "")
            if not vid:
                raise PublishUnconfirmed("Facebook returned no video id")
            self._save(pub, video_id=vid, step="started")
            size = os.path.getsize(clip.render_path)
            with open(clip.render_path, "rb") as f:
                r = http().post(f"{RUPLOAD}/{vid}", content=f.read(), headers={
                    "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size),
                    "Content-Type": "application/octet-stream"})
            if not _check(r, "upload").get("success"):
                raise PublishUnconfirmed("Facebook did not accept the upload")
            self._save(pub, step="uploaded")
        if (pub.platform_state or {}).get("step") == "uploaded":
            meta = (clip.features or {}).get("metadata") or {}
            fin = _check(http().post(f"{GRAPH}/{page}/video_reels", json={
                "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
                "title": (clip.title or "")[:255], "description": clip.description[:2200],
                "is_ai_generated": bool((clip.features or {}).get("synthetic", False)),
                "access_token": token}), "finish")
            if not fin.get("success"):
                raise PublishUnconfirmed("Facebook did not accept the publish request")
            self._save(pub, step="finished", paid_promotion=bool(meta.get("paid_promotion")))
        conf = self._confirm(vid, token, CONFIRM_WAIT_S)
        if conf is None:
            raise PlatformBusy("Facebook is still processing the reel; checking again shortly", 300)
        return conf

    def lookup(self, account: SocialAccount, pub: Publication):
        state = pub.platform_state or {}
        vid = state.get("video_id")
        if not vid:
            return None  # never reached Facebook
        if state.get("step") != "finished":
            return None  # not published yet: publish() resumes from the saved step
        conf = self._confirm(vid, self._token(account), 0)
        if conf is None:
            raise PlatformBusy("Facebook is still processing the reel", 300)
        return conf

    def stats(self, account: SocialAccount, post_ids: list[str]) -> dict[str, dict]:
        token = self._token(account)
        out: dict[str, dict] = {}
        for vid in post_ids:
            r = http().get(f"{GRAPH}/{vid}/video_insights", params={
                "metric": "blue_reels_play_count,post_video_social_actions", "access_token": token})
            if r.status_code == 400:  # metric names differ for some videos: fall back to the documented one
                r = http().get(f"{GRAPH}/{vid}/video_insights",
                               params={"metric": "total_video_views", "access_token": token})
            data = _check(r, "video_insights").get("data", [])
            row = {"views": 0, "likes": 0, "comments": 0, "shares": 0}
            for m in data:
                val = (m.get("values") or [{}])[-1].get("value", 0)
                if m.get("name") in ("blue_reels_play_count", "total_video_views"):
                    row["views"] = int(val or 0)
                elif m.get("name") == "post_video_social_actions" and isinstance(val, dict):
                    row["comments"] = int(val.get("COMMENT", 0))
                    row["shares"] = int(val.get("SHARE", 0))
                    row["likes"] = int(val.get("LIKE", 0))
            out[vid] = row
        return out
