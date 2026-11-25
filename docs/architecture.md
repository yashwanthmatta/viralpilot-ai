# Architecture and failure handling

## Design choices

**PostgreSQL is the source of truth; Redis is a doorbell.** Every unit of work
is a row in `jobs` with a status, attempt count, `run_after` time and lease.
Celery messages carry only a job id. If Redis is flushed or a message is lost,
the supervisor re-sends due jobs on its next tick. Workers claim a job with a
single conditional `UPDATE … WHERE status='pending'`, so a duplicate message
can never run a job twice.

**Deterministic first, AI second.** Polling, rights checks, de-duplication,
scheduling, budget checks and retries are plain code. Model calls are reserved
for steps that need judgement (clip ranking, hooks, metadata), and each one goes
through the budget guard.

**One always-on worker process.** `celery worker -B --concurrency=1` runs the
beat scheduler and the worker together, which is the cheapest 24/7 shape. Video
jobs are long and CPU-bound, so one at a time is the right default; scale by
adding worker instances (and moving beat to its own process) later.

**Agents are stages, not chatbots.** The ten agents map onto job kinds and
supervisor duties. They communicate through database state, not by calling
each other.

## Job lifecycle

```
enqueue (dedupe_key unique) ──▶ pending ──claim──▶ running ──▶ succeeded
                                  ▲   │                 │
                     backoff ─────┘   │                 ├─ StageBlocked ──▶ blocked (needs an external fix)
                                      │                 ├─ RetryLater ────▶ pending (rate limit / not yet time; no attempt used)
       autopilot stopped ─────────────┘                 ├─ BudgetExceeded ▶ pending until next day + dashboard blocker
                                                        └─ other error ───▶ pending with backoff, or failed (dead letter)
lease expired (worker crashed) ──▶ pending (counts as an attempt)
```

## What happens when…

| Event | Behaviour |
|---|---|
| Worker crashes mid-job | Lease expires (`JOB_LEASE_S`, default 15 min); supervisor puts it back; it retries. Celery `acks_late` + `reject_on_worker_lost` also redeliver the message. |
| Server restarts | Nothing is lost: jobs are in Postgres. Beat resumes ticking; due jobs are re-dispatched. |
| Redis wiped | Supervisor re-dispatches all due jobs on the next tick. |
| Platform rate-limits | Stage raises `RetryLater` with the platform's `Retry-After`. |
| Crash after the platform accepted an upload | Publication stays `publishing`. Next attempt calls the adapter's `lookup()` to find the existing post. If the adapter can't look up, it stops and raises a dashboard blocker rather than risk a duplicate. |
| Budget reached | Paid steps are refused before the call is made; jobs wait until the period resets. Free work (polling, recovery) continues. |
| STOP AUTOPILOT | Flag flips in the DB; each job checks it before starting and goes back to pending untouched. Nothing is deleted; START resumes. |
| Stage not built yet | Job is `blocked`, a blocker appears on the dashboard, and the job resumes when the stage ships (`unblock`). |

## Security

- Owner login: argon2 hash in env, signed HttpOnly session cookie, 5 attempts / 5 min per IP.
- CSRF: state-changing requests need `X-VP-CSRF: 1`; CORS allows only `WEB_ORIGIN`.
- SSRF: user-supplied URLs must be https and resolve only to public IPs; each redirect hop is re-checked.
- XML: feeds parsed with `defusedxml` (no entity expansion).
- Downloads: size-capped, streamed to disk, SHA-256 de-duplicated.
- Secrets: env vars only; OAuth tokens Fernet-encrypted with `CREDENTIALS_KEY`.
- Audit log of logins and all configuration changes.
- Unauthorised publishing is blocked three ways: per-account permission switch, adapter availability, and the confirm-or-raise contract.
