# ViralPilot AI

An autonomous, rights-checked short-form video pipeline for personal use. You
configure it once (sources you're allowed to use, social accounts, spending
limits), press **START AUTOPILOT**, and cloud workers discover, process,
quality-check, publish and learn without a browser or laptop being on.

> **Status:** Phase 1 (foundation) is built and tested. The video engine,
> publishing adapters and growth engine are the next phases. See
> [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md) for exactly what works today,
> and [SETUP_REQUIRED.md](SETUP_REQUIRED.md) for what only you can do.

## Ground rules the code enforces

- **Default-deny rights gate.** Only content you own, have written permission
  for, or that carries a commercial-reuse licence (CC BY / BY-SA / CC0 / public
  domain / paid library) is processed. NC, ND and unclear licences are rejected.
- **Official APIs only.** No scraping of platforms, no bypassing app audits or
  consent requirements. Platforms that don't allow unattended posting are
  marked *blocked* and skipped; the rest keep going.
- **Confirmed publishing only.** A video is "published" only when the platform
  returns its own post ID. Interrupted uploads are checked before any retry so
  nothing is double-posted.
- **Hard spending limits.** Every paid step reserves its cost first. Daily,
  monthly and per-video ceilings are enforced inside a database lock.
- **No invented numbers.** Every figure on the dashboard comes from the
  database or a platform API. Missing data shows as "n/a".

## Architecture

```
 apps/web (Next.js static, served by the API) ──same-origin cookie──▶ apps/api (FastAPI)
                                                              │
                                                     PostgreSQL (source of truth)
                                                              ▲
 apps/worker (Celery worker + beat, always on) ◀── Redis ─────┘ (wake-ups only)
   │  supervisor tick every 60s: recover crashed jobs, schedule discovery,
   │  refresh blockers, dispatch due jobs
   └─ runs stage handlers from packages/agents
```

| Path | What it is |
|---|---|
| `apps/web` | Next.js 16 + React 19 + Tailwind 4 dashboard (shadcn-style components) |
| `apps/api` | FastAPI JSON API: auth, monitoring, one-time configuration |
| `apps/worker` | Celery app: `vp.run_job` and the `vp.supervisor_tick` beat task |
| `packages/shared` | Config, SQLAlchemy models, durable job queue, budget guard, SSRF-safe HTTP, encryption |
| `packages/agents` | Supervisor, rights gate, stage handlers (acquisition, publishing, …) |
| `packages/publishing` | Platform adapters behind a strict confirm-or-raise contract |
| `packages/video` | FFmpeg/whisper engine (phase 2) |
| `packages/analytics` | Growth engine (phase 5) |
| `migrations` | Alembic migrations |
| `infrastructure` | Dockerfiles, env templates, Render blueprint |
| `tests` | Unit tests (SQLite or Postgres) and integration tests (real Postgres + Redis + Celery) |

How the pipeline survives failures: [docs/architecture.md](docs/architecture.md).
Platform approval requirements: [PLATFORM_COMPLIANCE.md](PLATFORM_COMPLIANCE.md).
Money: [REVENUE_STRATEGY.md](REVENUE_STRATEGY.md) · [BUSINESS_REVIEW.md](BUSINESS_REVIEW.md).
Proof: [TEST_RESULTS.md](TEST_RESULTS.md) · Hosting: [FREE_MODE.md](FREE_MODE.md) ($0) or [DEPLOYMENT.md](DEPLOYMENT.md) (≈ $33.50/month, faster).

## Run it locally

```bash
cp infrastructure/env/development.env.example .env
python scripts/gen_secrets.py          # paste SECRET_KEY and CREDENTIALS_KEY into .env
python scripts/hash_password.py        # paste the hash into ADMIN_PASSWORD_HASH
docker compose up --build              # dashboard on http://localhost:3000, API on :8000
```

Without Docker:

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
alembic upgrade head
uvicorn vp_api.app:app --reload                                   # API
celery -A vp_worker.celery_app worker -B --concurrency=1         # worker
cd apps/web && npm ci && npm run dev                              # dashboard
```

## Tests

```bash
pytest -q tests/unit                                   # fast, SQLite
TEST_DATABASE_URL=postgresql://… pytest -q tests/unit  # same tests on Postgres
INTEGRATION_DATABASE_URL=postgresql://… INTEGRATION_REDIS_URL=redis://… pytest -q tests/integration
```

CI runs all of these plus lint, migrations check, the web build, pip-audit,
bandit, npm audit, gitleaks and CodeQL.
