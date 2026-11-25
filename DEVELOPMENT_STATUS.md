# Development status

_Last updated: 2026-11-25 (phase 4b: Facebook Reels)_

## Acceptance test status

**Not passed.** The zero-touch acceptance test still needs at least one
approved publishing integration with real credentials (phase 4), real campaign credentials (Whop OAuth) and real
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

- `pytest tests` on PostgreSQL 16 + real Redis + real Celery worker: **116 passed**
- `pytest tests/unit` on SQLite: **114 passed**
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

## Phase 3b — Quality control, metadata, scheduling: done

| Area | State | Evidence |
|---|---|---|
| QC measured on the rendered file: resolution, frame rate, duration, audio/video streams, loudness (EBU R128), dead air, black frames, frozen video, captions, cover | done | `test_quality.py` on real FFmpeg renders |
| Bounded regeneration: fixable failures re-render once (`QC_MAX_ATTEMPTS`), others are discarded with the reason | done | `test_quality.py`, pipeline test |
| Metadata by Claude (`METADATA_MODEL`, default `claude-opus-5-5` at low effort, structured JSON output, server-side refusal fallback) with budget reservation and the real cost from `usage` | done; real API not called here (no key in this sandbox) | `test_quality.py` with a fake client |
| Rules writer used when there is no key, the budget can't cover the call, or the model fails | done | `test_quality.py` |
| Non-optional rules: `#ad` and "Paid partnership" for campaign clips, CC BY attribution, `#Shorts`, title limits, engagement-bait removal | done | `test_quality.py` |
| Scheduling onto accounts with publishing allowed, spaced by each account's posts-per-day | done | `test_video_pipeline.py` |
| Blocked jobs re-check themselves every 30 min and clear their dashboard blocker when they succeed | done | `test_worker.py` |
| Video library: in-browser preview (served only from `MEDIA_DIR`, login required), QC results, hook, description, cost | done | `test_revenue_api.py`, `next build` |

## Phase 4 — YouTube publishing: done (needs your Google OAuth client)

| Area | State | Evidence |
|---|---|---|
| OAuth connect (state cookie, offline access), tokens encrypted with `CREDENTIALS_KEY`, automatic refresh | done | `test_youtube.py` |
| Resumable `videos.insert`; published only when YouTube returns the video id | done | `test_youtube.py` (mocked Google API) |
| Duplicate protection: interrupted uploads are found by their `vp-…` tag before any retry | done | `test_youtube.py` |
| Paid placement flag on campaign clips | done | `test_youtube.py` |
| Quota exceeded waits 6 h; revoked access pauses the account and asks for reconnect | done | `test_youtube.py` |
| Metrics at 1 h, 24 h, 72 h, 7 d, 30 d from `videos.list` statistics | done | `test_youtube.py` |
| Publications blocked by a platform keep their place and re-check every 30 min | done | `test_publishing.py` |
| A real upload to a real channel | **not done**: needs your Google Cloud OAuth client and channel | — |

## Phase 4b — Facebook Reels publishing: done (needs your Meta app)

| Area | State | Evidence |
|---|---|---|
| Page connect via Facebook Login; only Pages where you can create content; Page tokens encrypted | done | `test_facebook.py` |
| Reels Publishing API: start → upload → finish, each step saved (`publications.platform_state`, migration 0004) so a crash resumes instead of posting twice | done | `test_facebook.py` |
| Confirmed only when Meta reports `publish_status = published`; still-processing reels are re-checked | done | `test_facebook.py` |
| Reel metrics (plays, comments, shares) | done | `test_facebook.py` |
| A real reel on a real Page | **not done**: needs your Meta app and Page | — |

## Free mode ($0): done

GitHub Actions scheduled batch worker (`vp_worker.batch`, `.github/workflows/autopilot.yml`), Neon Postgres, media in the Actions cache, dashboard on Render's free plan or locally, rules writer instead of paid AI. See [FREE_MODE.md](FREE_MODE.md). Tested by `test_batch.py`.

## Remaining phases

| Phase | Scope | Blocked by |
|---|---|---|
| 2b — Storage | R2/S3 upload of renders with lifecycle rules | an R2 bucket (cloud deploy only) |
| 3c — Intelligence | trend signals, niche research, original faceless video generation with TTS | Claude/OpenAI API keys; TTS provider key |
| 4c — More platforms | Instagram Reels (same Meta app), TikTok Content Posting if audited | platform app approvals ([PLATFORM_COMPLIANCE.md](PLATFORM_COMPLIANCE.md)) |
| 5 — Growth engine | metrics collection, per-dimension performance, controlled experiments (explore/exploit), automatic strategy weights | phase 4 + real published videos |
| 6 — Cloud deploy | packaged: one Render service (API + dashboard + worker + scheduler), Postgres, Key Value, disk; see DEPLOYMENT.md | your approval of ≈ $33.50/month; your Render account |
| 7 — Validation | real end-to-end acceptance run, failure-injection, cost review | phases 2–6 |

## Known limitations

- Login rate limiting is in-memory per API instance (fine for one instance).
- Media is stored on the worker's disk; phase 2 moves it to R2/S3.
- Revenue only appears once recorded with evidence or reported by the Whop API; nothing is estimated in the ledger.
- Content Rewards and Vyro have no public clipper API, so their submissions are manual.
