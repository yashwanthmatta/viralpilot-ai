import os

import pytest
from argon2 import PasswordHasher

TEST_HASH = PasswordHasher().hash("test-pass")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    pg = os.environ.get("TEST_DATABASE_URL")
    monkeypatch.setenv("DATABASE_URL", pg or f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", TEST_HASH)
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DAILY_LIMIT_USD", "1.00")
    monkeypatch.delenv("WHOP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("CAMPAIGN_FEED_URLS", raising=False)
    monkeypatch.delenv("OPERATOR_COUNTRY", raising=False)
    monkeypatch.setenv("MONTHLY_LIMIT_USD", "5.00")
    for k in ("TOTAL_LIMIT_USD", "PER_VIDEO_LIMIT_USD", "MAX_VIDEOS_CEILING", "MAX_VIDEOS_PER_DAY"):
        monkeypatch.delenv(k, raising=False)
    from vp_agents import dispatch
    from vp_shared import db

    db.init_engine()
    if pg:
        db.Base.metadata.drop_all(db.engine())
    db.create_all()
    sent: list[int] = []
    dispatch.set_dispatcher(sent.append)
    yield sent
    dispatch.set_dispatcher(None)


@pytest.fixture
def s():
    from vp_shared import db

    with db.session_scope() as session:
        yield session


def start_autopilot():
    from vp_shared import db
    from vp_shared.events import set_autopilot

    with db.session_scope() as s:
        set_autopilot(s, True, "test")
