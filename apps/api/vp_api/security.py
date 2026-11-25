"""Single-owner authentication for the dashboard API.

* Password is checked against an argon2 hash from ADMIN_PASSWORD_HASH (the
  plain password is never stored anywhere).
* A successful login sets an HttpOnly, Secure, signed session cookie.
* Every state-changing request must also carry the ``X-VP-CSRF: 1`` header.
  Browsers can't send custom headers cross-origin without a CORS preflight,
  and CORS only allows WEB_ORIGIN, so other sites can't forge requests.
* Login attempts are rate limited per IP (in memory per API instance).
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from vp_shared.config import get_settings

COOKIE = "vp_session"
CSRF_HEADER = "x-vp-csrf"
_ph = PasswordHasher()
_attempts: dict[str, deque] = defaultdict(deque)
LOGIN_WINDOW_S = 300
LOGIN_MAX = 5


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def _signer() -> TimestampSigner:
    key = get_settings().secret_key
    if len(key) < 32:
        raise HTTPException(503, "SECRET_KEY is missing or shorter than 32 characters")
    return TimestampSigner(key, salt="vp-session")


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else ""))[:64]


def check_rate_limit(ip: str) -> None:
    q = _attempts[ip]
    now = time.monotonic()
    while q and now - q[0] > LOGIN_WINDOW_S:
        q.popleft()
    if len(q) >= LOGIN_MAX:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts; try again in a few minutes.")
    q.append(now)


def verify_password(pw: str) -> bool:
    h = get_settings().admin_password_hash
    if not h:
        raise HTTPException(503, "ADMIN_PASSWORD_HASH is not set; login disabled")
    try:
        return _ph.verify(h, pw)
    except (VerifyMismatchError, InvalidHashError):
        return False


def issue_session(response: Response) -> None:
    cfg = get_settings()
    token = _signer().sign(b"admin").decode()
    response.set_cookie(
        COOKIE, token, max_age=cfg.session_hours * 3600, httponly=True,
        secure=cfg.app_env != "development",
        samesite="none" if cfg.cookie_samesite == "none" and cfg.app_env != "development" else "lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def require_session(request: Request) -> str:
    token = request.cookies.get(COOKIE, "")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not signed in")
    try:
        _signer().unsign(token, max_age=get_settings().session_hours * 3600)
    except (BadSignature, SignatureExpired) as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired") from e
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "missing CSRF header")
    return "admin"
