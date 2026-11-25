# Development status

_Last updated: 2026-11-25 (phase 3a: paid campaign engine)_

## Acceptance test status

**Not passed.** The zero-touch acceptance test still needs the QC and
metadata stages (phase 3b), at least one approved publishing integration with
real credentials (phase 4), real campaign credentials (Whop OAuth) and real
metrics (phase 5). Nothing below claims otherwise. Tests
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
| Budget guard ($3/day, $90/month, $100 lifetime, $0.50/video, 3 videos/day, ceiling 5) | done | `test_budget.py`; the daily video cap is enforced in `edit.clip` |
| Rights gate (default deny, NC/ND rejected, attribution required) | done | `test_rights.py`, `test_acquisition.py` |
| RSS/Atom acquisition: discovery, de-dup by entry and file hash, size-capped safe download | done | `test_acquisition.py`, integration test |
| SSRF protection on all user-supplied URLs | done | `test_netsafety.py` |
| Publishing stage: permission switch, platform availability, daily cap, confirm-or-raise, crash-safe retry | done | `test_publishing.py` (fake adapter) |
| Platform adapters | report blocked honestly; real uploads are phase 4 | `/api/platforms` |
| Auth (argon2, signed cookie, CSRF header, login rate limit, audit log) | done | `test_supervisor_and_web.py` |
| JSON API for every dashboard view | done | `apps/api/vp_api/app.py` |
| Next.js dashboard: command center with START/STOP, activity, agents, discovery, library, publishing + calendar, accounts, sources, costs, system health + dead-letter queue, security/audit, settings | done | `npm run build` passes; all data comes from the API |
| Docker images + Compose, dev/staging/prod env templates, Render blueprint | done (not deployed) | `infrastructure/` |
| CI (lint, migrations, unit on SQLite + Postgres, integration with Redis + Celery, web lint/typecheck/build) | done | `.github/workflows/ci.yml` |
| Security scanning (pip-audit, bandit, npm audit, gitleaks, CodeQL, Dependabot) | done | `.github/workflows/security.yml` |

### Latest local test results

- `pytest tests` on PostgreSQL 16 + real Redis + real Celery worker: **87 passed**
- `pytest tests/unit` on SQLite: **85 passed**
- Alembic upgrade → downgrade → upgrade and `alembic check` on PostgreSQL 16: clean
- `ruff check .`: clean · `bandit`: no issues · `pip-audit`: no known vulnerabilities
- `npm run lint`, `typecheck`, `build`: pass · `npm audit --omit=dev`: 0 vulnerabilities
- API smoke test against Postgres: login, session, status, and CORS rejection of a foreign origin all behave as expected

## Phase 2 — Video engine: done

| Area | State | Evidence |
|---|---|---|
| ffprobe media info, FFmpeg scene and silence detection | done | `test_video_engine.py` on real generated media |
| faster-whisper transcription with word timestamps, cached by file SHA-256 | done (real model not run here: model download is blocked in this sandbox; tests use a fake transcriber) | `test_video_pipeline.py` |
| Explainable clip scoring and selection (15–59 s, overlap ≤ 30%) | done | `test_video_engine.py` |
| Edit plan: silence removal, punch-in zooms, keyword highlights | done | `test_video_engine.py` |
| Word-by-word ASS captions, face-aware 9:16 crop (OpenCV), −14 LUFS, 1080×1920 H.264 + cover | done | real FFmpeg render in tests |
| Pipeline stages `transcribe.item` → `clip.item` → `edit.clip` with budget reservations | done | `test_video_pipeline.py` |

## Phase 3a — Paid campaign engine and revenue tracking: done

| Area | State | Evidence |
|---|---|---|
| Whop Bounties adapter (official API: list open clipping bounties, create submissions, poll status) | done; needs your Whop OAuth token to run for real | `test_campaigns.py` (HTTP mocked) |
| Authorized JSON feed adapter | done | [docs/campaign-feed.md](docs/campaign-feed.md) |
| Manual campaigns (Content Rewards, Vyro, direct deals) with a manual submission queue | done | `/campaigns` page, `test_revenue_api.py` |
| Eligibility and fraud checks (ended, exhausted budget, suspicious payout, geography, platform, no publishable account, no footage) | done | `test_campaigns.py` |
| Risk-adjusted expected profit per clip, ranking, activation of top campaigns, footage intake as creator-authorized sources | done; numbers labeled **estimate** until real data exists | `test_campaigns.py` |
| Revenue ledger: pending vs confirmed kept apart, evidence required, idempotent external refs | done | `test_revenue_api.py` |
| Scaling engine (grows only on confirmed revenue) and daily strategy run that drops low-approval campaigns | done | `test_campaigns.py` |
| Milestone calculator ($1 → $100k/month), measured once ≥ 10 paid videos, otherwise labeled assumptions | done | `/revenue` page |
| Dashboard: Paid campaigns, Revenue, revenue stats on the command center, lifetime cap and scaling ceiling in Settings | done | `next build` passes |

## Remaining phases

| Phase | Scope | Blocked by |
|---|---|---|
| 2b — Storage | R2/S3 upload of renders with lifecycle rules | an R2 bucket (cloud deploy only) |
| 3b — Intelligence | Claude-based hook/metadata with model routing and caching, automated QC with bounded regeneration, trend signals, niche research, original faceless video generation with TTS | Claude/OpenAI API keys; TTS provider key |
| 4 — Publishing | OAuth (connect, encrypted storage, refresh), YouTube `videos.insert` + lookup, Instagram/Facebook Graph publishing, TikTok Content Posting, schedule optimiser | platform app approvals ([PLATFORM_COMPLIANCE.md](PLATFORM_COMPLIANCE.md)) |
| 5 — Growth engine | metrics collection, per-dimension performance, controlled experiments (explore/exploit), automatic strategy weights | phase 4 + real published videos |
| 6 — Cloud deploy | Render (API, worker, Postgres, Key Value, disk) + Vercel | your approval of the monthly cost; account access |
| 7 — Validation | real end-to-end acceptance run, failure-injection, cost review | phases 2–6 |

## Known limitations

- Login rate limiting is in-memory per API instance (fine for one instance).
- Media is stored on the worker's disk; phase 2 moves it to R2/S3.
- Revenue only appears once recorded with evidence or reported by the Whop API; nothing is estimated in the ledger.
- Content Rewards and Vyro have no public clipper API, so their submissions are manual.
