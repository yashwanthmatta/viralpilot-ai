"""Encryption for stored platform credentials (OAuth refresh tokens).

Tokens are encrypted with Fernet using CREDENTIALS_KEY, which lives only in
the hosting provider's secret env vars, never in the database or the repo.
Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import json

from cryptography.fernet import Fernet


class CredentialsKeyMissing(RuntimeError):
    pass


def _fernet() -> Fernet:
    from vp_shared import keys

    try:
        return Fernet(keys.fernet_key())
    except Exception as e:  # noqa: BLE001 - no env key and no database
        raise CredentialsKeyMissing(f"no credentials key available: {e}") from e


def encrypt(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt(token: str) -> dict:
    return json.loads(_fernet().decrypt(token.encode()).decode())
