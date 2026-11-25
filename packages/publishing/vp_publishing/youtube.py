"""YouTube Shorts publishing through the official YouTube Data API v3.

* OAuth 2.0 (web server flow, offline access). Refresh tokens are stored
  encrypted with CREDENTIALS_KEY; access tokens are refreshed when needed.
* Upload: resumable ``videos.insert``. A video counts as published only when
  YouTube returns its video id.
* Duplicate protection: every upload carries a private-to-us tag
  ``vp-<idempotency key>``. Before retrying an interrupted upload, the
  channel's recent uploads are searched for that tag.
* Metrics: ``videos.list`` statistics (views, likes, comments).

Everything here talks to fixed Google hosts; no user-supplied URL is fetched.
"""
from __future__ import annotations

import os
import time
from collections.abc import Iterator
from urllib.parse import urlencode

import httpx
from vp_shared import crypto
from vp_shared.models import Clip, Publication, SocialAccount

from . import AccountNeedsReconnect, Availability, Confirmation, PlatformBusy, Publisher, PublishUnconfirmed

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105  # nosec B105
API = "https://www.googleapis.com/youtube/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
CHUNK = 8 * 1024 * 1024


class TokenRevoked(AccountNeedsReconnect):
    """The owner revoked access or the refresh token expired: reconnect needed."""


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def configured() -> bool:
    return bool(_env("GOOGLE_CLIENT_ID") and _env("GOOGLE_CLIENT_SECRET") and _env("PUBLIC_API_URL"))


def redirect_uri() -> str:
    return _env("PUBLIC_API_URL").rstrip("/") + "/api/oauth/youtube/callback"


def auth_url(state: str) -> str:
    return AUTH_URL + "?" + urlencode({
        "client_id": _env("GOOGLE_CLIENT_ID"), "redirect_uri": redirect_uri(), "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true", "state": state,
    })


_http: httpx.Client | None = None


def set_http(client: httpx.Client | None) -> None:
    """Tests install an httpx client with a MockTransport here."""
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
            msg = err.get("message") if isinstance(err, dict) else str(err)
            reason = (err.get("errors") or [{}])[0].get("reason", "") if isinstance(err, dict) else ""
        except ValueError:
            msg, reason = r.text[:300], ""
        if r.status_code in (401, 403) and reason in ("quotaExceeded", "uploadLimitExceeded", "rateLimitExceeded"):
            raise QuotaExceeded(f"YouTube {what}: {reason}", 6 * 3600)
        raise httpx.HTTPStatusError(f"{what} failed ({r.status_code}): {msg}", request=r.request, response=r)
    return r.json() if r.content else {}


class QuotaExceeded(PlatformBusy):
    pass


def exchange_code(code: str) -> dict:
    r = http().post(TOKEN_URL, data={
        "code": code, "client_id": _env("GOOGLE_CLIENT_ID"), "client_secret": _env("GOOGLE_CLIENT_SECRET"),
        "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})
    tok = _check(r, "token exchange")
    if not tok.get("refresh_token"):
        raise PublishUnconfirmed("Google returned no refresh token; remove the app's access in your Google "
                                 "account and connect again")
    return {"access_token": tok["access_token"], "refresh_token": tok["refresh_token"],
            "expires_at": time.time() + int(tok.get("expires_in", 3600)), "scope": tok.get("scope", "")}


def channel_info(access_token: str) -> dict:
    r = http().get(f"{API}/channels", params={"part": "snippet,contentDetails", "mine": "true"},
                   headers={"Authorization": f"Bearer {access_token}"})
    items = _check(r, "channels.list").get("items", [])
    if not items:
        raise PublishUnconfirmed("this Google account has no YouTube channel")
    ch = items[0]
    return {"id": ch["id"], "title": ch["snippet"]["title"],
            "uploads": ch["contentDetails"]["relatedPlaylists"]["uploads"]}


def _file_chunks(path: str) -> Iterator[bytes]:
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            yield chunk


def idempotency_tag(pub: Publication) -> str:
    return f"vp-{pub.idempotency_key}"[:60]


class YouTubePublisher(Publisher):
    platform = "youtube"
    oauth = True

    def platform_status(self) -> Availability:
        if not configured():
            return self.availability(SocialAccount(platform="youtube"))
        return Availability(True, reason="Official YouTube Data API upload is set up. Connect a channel and "
                                         "allow publishing to it.")

    # ---------------------------------------------------------------- tokens
    def _creds(self, account: SocialAccount) -> dict:
        return crypto.decrypt(account.encrypted_credentials)

    def access_token(self, account: SocialAccount) -> str:
        creds = self._creds(account)
        if creds.get("expires_at", 0) - 120 > time.time():
            return creds["access_token"]
        r = http().post(TOKEN_URL, data={
            "client_id": _env("GOOGLE_CLIENT_ID"), "client_secret": _env("GOOGLE_CLIENT_SECRET"),
            "refresh_token": creds["refresh_token"], "grant_type": "refresh_token"})
        if r.status_code == 400 and "invalid_grant" in r.text:
            raise TokenRevoked("YouTube access was revoked or expired; connect the channel again")
        tok = _check(r, "token refresh")
        creds["access_token"] = tok["access_token"]
        creds["expires_at"] = time.time() + int(tok.get("expires_in", 3600))
        account.encrypted_credentials = crypto.encrypt(creds)
        return creds["access_token"]

    def _auth(self, account: SocialAccount) -> dict:
        return {"Authorization": f"Bearer {self.access_token(account)}"}

    # ---------------------------------------------------------------- contract
    def availability(self, account: SocialAccount) -> Availability:
        key = "platform.youtube"
        if not configured():
            return Availability(False, key, "Google OAuth client is not configured (GOOGLE_CLIENT_ID, "
                                            "GOOGLE_CLIENT_SECRET, PUBLIC_API_URL).")
        if not account.encrypted_credentials:
            return Availability(False, f"account.{account.id}.connect",
                                "Channel not connected yet: use Connect YouTube on the Social accounts page.")
        try:
            creds = self._creds(account)
        except Exception:  # noqa: BLE001 - wrong CREDENTIALS_KEY or corrupted value
            return Availability(False, f"account.{account.id}.connect",
                                "Stored YouTube credentials can't be decrypted; connect the channel again.")
        if "youtube.upload" not in creds.get("scope", "youtube.upload"):
            return Availability(False, f"account.{account.id}.connect", "Upload permission was not granted.")
        if account.health == "paused" and "reconnect" in (account.health_note or ""):
            return Availability(False, f"account.{account.id}.connect", account.health_note)
        return Availability(True)

    def publish(self, account: SocialAccount, clip: Clip, pub: Publication) -> Confirmation:
        brand = account.brand or {}
        meta = (clip.features or {}).get("metadata") or {}
        tags = [t.lstrip("#") for t in (clip.hashtags or []) if t.lstrip("#")][:15] + [idempotency_tag(pub)]
        body: dict = {
            "snippet": {"title": (clip.title or "New short")[:100], "description": clip.description[:4900],
                        "tags": tags, "categoryId": str(brand.get("category_id", "22"))},
            "status": {"privacyStatus": brand.get("privacy", "public"), "selfDeclaredMadeForKids": False,
                       "containsSyntheticMedia": bool((clip.features or {}).get("synthetic", False))},
        }
        parts = "snippet,status"
        if meta.get("paid_promotion"):
            body["paidProductPlacementDetails"] = {"hasPaidProductPlacement": True}
            parts += ",paidProductPlacementDetails"
        size = os.path.getsize(clip.render_path)
        h = self._auth(account)
        init = http().post(UPLOAD_URL, params={"uploadType": "resumable", "part": parts}, json=body,
                           headers={**h, "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
        _check(init, "videos.insert (start)")
        session_url = init.headers.get("Location", "")
        if not session_url.startswith("https://www.googleapis.com/upload/"):
            raise PublishUnconfirmed("YouTube did not return an upload session")
        r = http().put(session_url, content=_file_chunks(clip.render_path),
                       headers={**h, "Content-Type": "video/mp4", "Content-Length": str(size)})
        video = _check(r, "videos.insert (upload)")
        vid = (video.get("id") or "").strip()
        if not vid:
            raise PublishUnconfirmed("YouTube returned no video id")
        return Confirmation(vid, f"https://www.youtube.com/shorts/{vid}")

    def lookup(self, account: SocialAccount, pub: Publication):
        creds = self._creds(account)
        playlist = creds.get("uploads")
        if not playlist:
            return NotImplemented
        h = self._auth(account)
        items = _check(http().get(f"{API}/playlistItems", headers=h, params={
            "part": "contentDetails", "playlistId": playlist, "maxResults": 50}), "playlistItems.list").get("items", [])
        ids = [i["contentDetails"]["videoId"] for i in items]
        if not ids:
            return None
        vids = _check(http().get(f"{API}/videos", headers=h, params={"part": "snippet", "id": ",".join(ids)}),
                      "videos.list").get("items", [])
        tag = idempotency_tag(pub)
        for v in vids:
            if tag in (v.get("snippet", {}).get("tags") or []):
                return Confirmation(v["id"], f"https://www.youtube.com/shorts/{v['id']}")
        return None

    def stats(self, account: SocialAccount, post_ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        h = self._auth(account)
        for i in range(0, len(post_ids), 50):
            batch = post_ids[i:i + 50]
            vids = _check(http().get(f"{API}/videos", headers=h, params={"part": "statistics", "id": ",".join(batch)}),
                          "videos.list").get("items", [])
            for v in vids:
                st = v.get("statistics", {})
                out[v["id"]] = {"views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                                "comments": int(st.get("commentCount", 0))}
        return out
