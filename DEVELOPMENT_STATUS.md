# Development status

_Last updated: 2026-11-25 (phase 1)_

## Acceptance test status

**Not passed.** The zero-touch acceptance test needs the video engine (phase
2–3), at least one approved publishing integration with real credentials
(phase 4), and real metrics (phase 5). Nothing below claims otherwise. Tests
that use fake adapters prove our own safety logic only.

## Phase 1 — Foundation: done

| Area | State | Evidence |
|---|---|---|
| Monorepo (apps/, packages/, infrastructure/, migrations/, tests/, docs/) | done | this repo |
| PostgreSQL schema + Alembic migration `0001` | done | applied cleanly to PostgreSQL 16 and SQLite |
| Durable job queue (idempotent enqueue, atomic claim, leases, backoff, dead letter, blocked state) | done | `tests/unit/test_jobs.py`, `test_worker.py` |
| Celery worker + beat supervisor, Redis broker | done | `tests/integration/test_celery_pipeline.py` runs a real worker process |
| Crash recovery / resume after restart | done | lease-expiry test; acks_late + reject_on_worker_lost |
| Emergency stop | done | jobs check the flag before starting; test `test_paused_when_autopilot_off` |
| Budget guard (daily $5, monthly, per-video, 3 videos/day setting) | done | `test_budget.py`; the 3/day cap is stored and shown; it is enforced when the clip-selection stage lands (phase 3) |
| Rights gate (default deny, NC/ND rejected, attribution required) | done | `test_rights.py`, `test_acquisition.py` |
| RSS/Atom acquisition: discovery, de-dup by entry and file hash, size-capped safe download | done | `test_acquisition.py`, integration test |
| SSRF protection on all user-supplied URLs | done | `test_netsafety.py` |
| Publishing stage: permission switch, platform availability, daily cap, confirm-or-raise, crash-safe retry | done | `test_publishing.py` (fake adapter) |
| Platform adapters | report blocked honestly; real uploads are phase 4 | `/api/platforms` |
| Auth (argon2, signed cookie, CSRF header, login rate limit, audit log) | done | `test_supervisor_and_web.py` |
| JSON API for every dashboard view | done | `apps/api/vp_api/app.py` |
| Next.js dashboard: command center with START/STOP, activity, agents, discovery, library, publishing + calendar, accounts, sources, costs & revenue, system health + dead-letter queue, security/audit, settings | done | `npm run build` passes; all data comes from the API |
| Docker images + Compose, dev/staging/prod env templates, Render blueprint | done (not deployed) | `infrastructure/` |
| CI (lint, migrations, unit on SQLite + Postgres, integration with Redis + Celery, web lint/typecheck/build) | done | `.github/workflows/ci.yml` |
| Security scanning (pip-audit, bandit, npm audit, gitleaks, CodeQL, Dependabot) | done | `.github/workflows/security.yml` |

### Latest local test results

- `pytest tests` (SQLite unit + Postgres/Redis/Celery integration): **52 passed**
- Same unit suite on PostgreSQL 16: **50 passed**
- `ruff check .`: clean · `bandit`: no issues · `pip-audit`: no known vulnerabilities
- `npm run lint`, `typecheck`, `build`: pass · `npm audit --omit=dev`: 0 vulnerabilities
- API smoke test against Postgres: login, session, status, and CORS rejection of a foreign origin all behave as expected

## Remaining phases

| Phase | Scope | Blocked by |
|---|---|---|
| 2 — Video engine | faster-whisper transcription (cached per file hash), PySceneDetect, MediaPipe face tracking, 9:16 smart crop, silence removal, animated word-level captions, loudness normalisation, 1080p FFmpeg render, R2/S3 storage with lifecycle rules | nothing external (R2 bucket needed only for cloud deploy) |
| 3 — Intelligence | transparent clip scoring (hook, retention proxies, emotion, story, shareability, relevance, originality, A/V quality), Claude-based hook/metadata with model routing and caching, automated QC with bounded regeneration, trend signals, niche research, original faceless video generation with TTS | Claude/OpenAI API keys; TTS provider key |
| 4 — Publishing | OAuth (connect, encrypted storage, refresh), YouTube `videos.insert` + lookup, Instagram/Facebook Graph publishing, TikTok Content Posting, schedule optimiser | platform app approvals ([docs/platform-blockers.md](docs/platform-blockers.md)) |
| 5 — Growth engine | metrics collection, per-dimension performance, controlled experiments (explore/exploit), automatic strategy weights | phase 4 + real published videos |
| 6 — Cloud deploy | Render (API, worker, Postgres, Key Value, disk) + Vercel | your approval of the monthly cost; account access |
| 7 — Validation | real end-to-end acceptance run, failure-injection, cost review | phases 2–6 |

## Known limitations

- Login rate limiting is in-memory per API instance (fine for one instance).
- Media is stored on the worker's disk; phase 2 moves it to R2/S3.
- Revenue is shown as "n/a": no revenue API is integrated yet.
