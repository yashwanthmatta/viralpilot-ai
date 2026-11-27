"""Zero-config keys: generated once, stored in the database, shared by every process."""
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from vp_api import security
from vp_api.app import app
from vp_shared import crypto, keys


def test_generated_keys_are_stable_and_shared(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("CREDENTIALS_KEY", raising=False)
    sk = keys.secret_key()
    token = crypto.encrypt({"refresh_token": "abc"})
    keys.reset_cache()  # a different process (the GitHub worker) reads the same keys
    assert keys.secret_key() == sk and len(sk) >= 32
    assert crypto.decrypt(token) == {"refresh_token": "abc"}


def test_env_key_wins_and_any_string_works(monkeypatch):
    monkeypatch.setenv("CREDENTIALS_KEY", "just a long random phrase typed by a person 123")
    Fernet(keys.fernet_key())  # valid key derived from the phrase
    real = Fernet.generate_key().decode()
    monkeypatch.setenv("CREDENTIALS_KEY", real)
    assert keys.fernet_key() == real.encode()


def test_plain_admin_password(monkeypatch):
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("ADMIN_PASSWORD", "my-own-long-password")
    security._attempts.clear()
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": "wrong-password"}).status_code == 401
        assert c.post("/api/auth/login", json={"password": "my-own-long-password"}).status_code == 200
    monkeypatch.setenv("ADMIN_PASSWORD", "short")
    assert security._plain_password_hash() == ""
