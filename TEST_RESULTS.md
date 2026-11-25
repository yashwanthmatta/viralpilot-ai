# Test results

_Run 2026-11-25 on commit after phase 4b. Everything below was run, not assumed._

## What has been proven, and what hasn't

| Claim | Proven? | How |
|---|---|---|
| Job queue survives crashes, retries with backoff, dead-letters, never double-runs | yes | unit tests + real Celery/Redis/Postgres integration test |
| Budget caps ($3/day, $90/month, $100 lifetime, $0.50/video) stop paid work before it runs | yes | `test_budget.py`, `test_quality.py` |
| Rights gate rejects unlicensed / NC / ND footage | yes | `test_rights.py`, `test_acquisition.py` |
| Video engine produces 1080×1920 captioned, loudness-normalised shorts | yes, on synthetic media with real FFmpeg | `test_video_engine.py`, `test_video_pipeline.py` |
| QC measures real files and discards or re-renders bad ones | yes, on real FFmpeg output | `test_quality.py` |
| Transcription with the real faster-whisper model | **no** | model download is blocked in this build sandbox; the deployed worker downloads it on first use. Tests use a stand-in transcriber |
| Claude metadata with real API | **no** | no API key here; tests use a fake client that checks request shape and cost accounting |
| YouTube upload, OAuth, duplicate check, metrics | logic yes, **real upload no** | `test_youtube.py` against a mocked Google API. Needs your Google OAuth client |
| Facebook Reels upload, Page connect, metrics | logic yes, **real post no** | `test_facebook.py` against a mocked Graph API. Needs your Meta app |
| Whop bounty discovery and submission | logic yes, **real call no** | `test_campaigns.py` with mocked HTTP. Needs your Whop token |
| Revenue shown only from verified entries | yes | `test_revenue_api.py` |
| Whole stack runs as one service (API + dashboard + worker + scheduler) | yes, locally | smoke run below |
| Zero-touch acceptance test with real platforms and real money | **not passed** | needs the credentials in SETUP_REQUIRED.md |

Mocked integrations prove our own logic only. They are not proof that a
platform accepts the request; the first real upload is the proof.

## Automated suites

| Suite | Result |
|---|---|
| `pytest tests` on PostgreSQL 16 + Redis + a real Celery worker process | **116 passed** |
| `pytest tests/unit` on SQLite | **114 passed** |
| `alembic upgrade head` → `downgrade 0003` → `upgrade head` → `alembic check` on PostgreSQL 16 | clean |
| `ruff check .` | clean |
| `bandit -r packages apps/api apps/worker` | no issues |
| Web: `eslint`, `tsc --noEmit`, `next build`, static export build | pass |
| GitHub Actions CI + Security (pip-audit, bandit, npm audit, gitleaks, CodeQL) on phases 1–3b | green |

## Local smoke run of the deployable service

`scripts/run_all.sh` started the API (serving the dashboard), the Celery
worker and the beat scheduler against PostgreSQL and Redis, then the API was
driven with `curl`:

```
GET  /healthz                       200 {"ok":true,...}
GET  /                              200 text/html (dashboard), CSP header present
GET  /accounts/                     200
GET  /api/status (no session)       401
POST /api/auth/login (wrong pw)     401
POST /api/auth/login                200
POST /api/autopilot/start (no CSRF) 403
POST /api/autopilot/start           400 "Add an authorised source or a paid campaign before starting autopilot."
POST /api/campaigns (manual)        201 status=restricted "no connected account allowed to publish to ['youtube']"
POST /api/autopilot/start           200 {"enabled":true}
  … one minute later, real supervisor ticks ran:
  job strategy.daily     succeeded   "3 videos/day: only 0 videos in 14 days; not enough evidence yet"
  job discover.campaigns succeeded
  blockers: sources.none, accounts.none, campaigns.no_sources
POST /api/autopilot/stop            200 {"enabled":false}
```

Status reported $0.00 spend against $3.00 / $90.00 / $100.00 limits and $0.00
confirmed and pending revenue, which is correct: nothing was spent or earned.

## Free-tier batch mode

- `test_batch.py`: one batch run transcribes and clips a real FFmpeg-made
  video inline (no Redis). The next run renders, QCs and writes metadata, then
  parks the job until an account is connected.
- `python -m vp_worker.batch --max-seconds 60` against PostgreSQL with Redis
  pointed at a closed port finished in about 1 s: `{"ticks": 1, "outcomes": {}}`.
  This shows the free mode doesn't need Redis.
