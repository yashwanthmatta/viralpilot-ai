# Deployment

Nothing has been deployed and nothing has been bought. Deploying needs your
go-ahead on the monthly cost below and your Render account.

## Recommended: one Render service (24/7)

`infrastructure/render/render.yaml` creates:

| Resource | Render plan | Price (render.com/pricing, checked 2026-11-25) | Why |
|---|---|---|---|
| `viralpilot` web service: API + dashboard + worker + scheduler (`scripts/run_all.sh`) | 1 CPU / 2 GB | **$25/month** | 2 GB fits faster-whisper `base.en` and 1080p FFmpeg renders. Free web services sleep, so they can't run 24/7 |
| 10 GB disk at `/data` | $0.25/GB | **$2.50/month** | source media and renders; old files can be pruned |
| PostgreSQL 16 | 256 MB | **$6/month** | source of truth for jobs, money and audit log |
| Key Value (Redis) | Free | **$0** | queue wake-ups only; losing it never loses a job |
| Workspace | Hobby | **$0** | |
| **Fixed total** | | **≈ $33.50/month** | |

Serving the dashboard from the API keeps one origin, so login cookies are
first-party (no cross-site cookie problems in Safari/Firefox) and previews
work because the API and the renderer share the disk.

`render.split.yaml` (separate API and worker, ≈ $40–50/month) is kept for later
scale-out; it can't show previews.

### Variable costs (capped by the dashboard limits)

| Item | Estimate per video | Notes |
|---|---|---|
| Transcription (faster-whisper on the worker) | $0 | runs on the service CPU |
| Rendering (FFmpeg) | $0 | runs on the service CPU |
| Hooks/titles via Claude (`claude-opus-5-5`, low effort, one call) | ≈ $0.01–0.03 | reserved before the call, real cost recorded from `usage`. Set `METADATA_MODEL=claude-haiku-5-5` for ≈ $0.001. With no key, the free rules writer is used |
| YouTube / Facebook APIs | $0 | quota-limited, not billed |
| **Per video** | **≈ $0.03** | well under the $0.50 cap |

At 3–5 videos/day that's about $3–5/month of AI spend.

### How hosting fits your $90/month cap

The $3/day, $90/month and $100 lifetime limits in the app govern **variable**
spend (API calls). Hosting is a fixed bill from Render, not tracked by the app.
Hosting ≈ $33.50 + AI ≈ $5 ≈ **$39/month** all-in at the starting volume.
If you want the app's cap to cover everything, lower the monthly limit to
about $55 so hosting plus variable spend stays under $90.

## Steps (after you approve)

1. Render → Blueprints → New Blueprint Instance → this repo, `infrastructure/render/render.yaml`.
2. Fill the secret env vars (see SETUP_REQUIRED.md): `ADMIN_PASSWORD_HASH`,
   `SECRET_KEY`, `CREDENTIALS_KEY` (`python scripts/gen_secrets.py`,
   `python scripts/hash_password.py`), `PUBLIC_API_URL` and `WEB_ORIGIN`
   (both `https://<service>.onrender.com`), plus the platform keys you have.
3. Deploy. `alembic upgrade head` runs before each deploy.
4. Open the URL, log in, connect YouTube / Facebook, allow publishing,
   add sources or campaigns, press **START AUTOPILOT**.

Backups: Render Postgres paid plans include daily backups; `scripts/backup_db.sh`
makes an extra dump.

Rollback: Render keeps previous deploys; "Rollback" in the service's Events tab.
Database migrations have downgrades (`alembic downgrade -1`).
