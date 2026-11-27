"""Signing and encryption keys.

Preferred: SECRET_KEY and CREDENTIALS_KEY as host secrets. For a free,
zero-config setup they may be left unset: a strong random key is generated
once and kept in the database (``app_secrets``), so the dashboard and the
GitHub Actions worker, which share the database, use the same key.

Trade-off: with keys in the database, someone who obtains a copy of the
database could also decrypt the stored platform tokens. Set the env vars to
keep the key separate from the data.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets

from cryptography.fernet import Fernet
from sqlalchemy.exc import IntegrityError

from vp_shared import db
from vp_shared.models import AppSecret

_cache: dict[str, str] = {}


def _stored(name: str, make) -> str:
    if name in _cache:
        return _cache[name]
    with db.session_scope() as s:
        row = s.get(AppSecret, name)
        if row is None:
            s.add(AppSecret(name=name, value=make()))
            try:
                s.flush()
            except IntegrityError:  # another process created it first
                s.rollback()
            row = s.get(AppSecret, name)
        _cache[name] = row.value
    return _cache[name]


def reset_cache() -> None:
    _cache.clear()


def secret_key() -> str:
    env = os.environ.get("SECRET_KEY", "")
    return env if env else _stored("secret_key", lambda: secrets.token_urlsafe(48))


def fernet_key() -> bytes:
    env = os.environ.get("CREDENTIALS_KEY", "")
    raw = env if env else _stored("credentials_key", lambda: Fernet.generate_key().decode())
    try:
        Fernet(raw.encode())
        return raw.encode()
    except ValueError:
        # Any long random string works: derive a valid Fernet key from it.
        return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
