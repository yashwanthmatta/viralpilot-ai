"""Encryption for stored platform credentials (OAuth refresh tokens).

Tokens are encrypted with Fernet using CREDENTIALS_KEY, which lives only in
the hosting provider's secret env vars, never in the database or the repo.
Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import json

from cryptography.fernet import Fernet

from vp_shared.config import get_settings


class CredentialsKeyMissing(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_settings().credentials_key
    if not key:
        raise CredentialsKeyMissing("CREDENTIALS_KEY is not set")
    return Fernet(key.encode())


def encrypt(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt(token: str) -> dict:
    return json.loads(_fernet().decrypt(token.encode()).decode())
