"""Runtime settings, read once from the environment.

Every secret comes from the environment (Render env vars / secret files in
production). Nothing secret is ever written to the database in plain text:
OAuth tokens are encrypted with ``CREDENTIALS_KEY`` (see ``crypto.py``).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", "sqlite:///./viralpilot.db"))
    redis_url: str = field(default_factory=lambda: os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    app_env: str = field(default_factory=lambda: os.environ.get("APP_ENV", "development"))
    # argon2 hash of the dashboard password (scripts/hash_password.py makes one).
    admin_password_hash: str = field(default_factory=lambda: os.environ.get("ADMIN_PASSWORD_HASH", ""))
    # Signs session cookies. Long random string; rotate to log everyone out.
    secret_key: str = field(default_factory=lambda: os.environ.get("SECRET_KEY", ""))
    # Exact origin of the Next.js dashboard, for CORS (e.g. https://viralpilot.vercel.app).
    web_origin: str = field(default_factory=lambda: os.environ.get("WEB_ORIGIN", "http://localhost:3000"))
    session_hours: int = field(default_factory=lambda: _int("SESSION_HOURS", 12))
    credentials_key: str = field(default_factory=lambda: os.environ.get("CREDENTIALS_KEY", ""))
    media_dir: str = field(default_factory=lambda: os.environ.get("MEDIA_DIR", "./media"))

    # Hard spending ceilings. These are the defaults the first time the
    # database is created; afterwards the values stored in BudgetSettings win
    # (the dashboard edits those). The worker refuses any paid step that would
    # cross either ceiling.
    default_daily_limit_usd: float = field(default_factory=lambda: _float("DAILY_LIMIT_USD", 5.0))
    default_monthly_limit_usd: float = field(default_factory=lambda: _float("MONTHLY_LIMIT_USD", 30.0))

    # Initial production cap: unique videos produced per day, spread across platforms.
    default_max_videos_per_day: int = field(default_factory=lambda: _int("MAX_VIDEOS_PER_DAY", 3))

    # Supervisor / job behaviour.
    supervisor_interval_s: int = field(default_factory=lambda: _int("SUPERVISOR_INTERVAL_S", 60))
    job_lease_s: int = field(default_factory=lambda: _int("JOB_LEASE_S", 900))
    job_max_attempts: int = field(default_factory=lambda: _int("JOB_MAX_ATTEMPTS", 4))
    discovery_interval_s: int = field(default_factory=lambda: _int("DISCOVERY_INTERVAL_S", 3600))
    # Set only in tests / local dev to allow fetching from private hosts.
    allow_private_network: bool = field(default_factory=lambda: os.environ.get("ALLOW_PRIVATE_NETWORK", "") == "1")
    max_import_bytes: int = field(default_factory=lambda: _int("MAX_IMPORT_BYTES", 500 * 1024 * 1024))


def get_settings() -> Settings:
    return Settings()
