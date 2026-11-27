# Running ViralPilot for $0

Free mode uses only free plans. Nothing here asks you to pay. Check each
sign-up page yourself: providers sometimes change their free plans or ask for
a card.

| Part | Paid layout (DEPLOYMENT.md) | Free layout |
|---|---|---|
| Worker (clipping, editing, publishing, metrics) | always-on Render service | **GitHub Actions** scheduled run every 3 h (`.github/workflows/autopilot.yml`) |
| Database | Render Postgres | **Neon** free Postgres |
| Queue | Redis | none (batch mode runs jobs in-process) |
| Media between runs | Render disk | **GitHub Actions cache** (10 GB per repo, pruned automatically) |
| Dashboard + OAuth callback | Render paid service | **Render free web service** (sleeps when idle), or run it on your own computer |
| Transcription | faster-whisper on the server | faster-whisper `base.en` on the GitHub runner |
| Hooks/titles | Claude (≈ $0.03/video) | **built-in rules writer** (free). Add `ANTHROPIC_API_KEY` later if you want Claude |

## Keys and password without scripts

If `SECRET_KEY` and `CREDENTIALS_KEY` aren't set, the app makes strong random
keys on first start and keeps them in the database, so the dashboard and the
GitHub worker share them automatically. The trade-off is that anyone with a
copy of the database could also decrypt the stored platform tokens. Setting
both as host secrets keeps the key separate from the data.

For login you can set `ADMIN_PASSWORD` (your own password, at least 10
characters) instead of a hash.

## Trade-offs, plainly

- **Slower.** Work happens in bursts every 3 hours, not continuously. A new
  campaign's first clip is typically posted within 3–9 hours instead of within
  an hour. Posting times land on the 3-hour schedule.
- **Minute budget.** A private repo gets 2,000 free GitHub Actions minutes a
  month. Eight runs a day at 3 videos/day is about 700–1,100 minutes. Above
  roughly 5 videos/day you'll run out. Options then: make the repo public
  (unlimited minutes, but your code becomes public; secrets stay private), or
  move to the paid layout.
- **Long source videos.** Transcribing a 1-hour episode on a free runner takes
  10–20 minutes. Prefer campaign footage or shorter sources.
- **Dashboard sleeps.** The free Render service takes up to a minute to wake
  when you open it. Publishing doesn't depend on it. Previews of rendered clips
  aren't available in free mode, because the files live in the Actions cache
  and not on the dashboard server.
- **Plainer titles.** The rules writer takes the hook from the clip's own
  strongest line. It's accurate, but less punchy than Claude.
- **Limits.** Neon's free database is small (about 0.5 GB). That's plenty for
  this app, since videos aren't stored in the database.

The money rules don't change in free mode. Posts are counted as published
only when the platform confirms them, revenue is counted only with evidence,
and views are never bought.

## Shortest path to the first real post

You need four free accounts. GitHub you already have.

1. **Neon** (neon.tech): create a project and copy its connection string.
2. **Google Cloud** (console.cloud.google.com) and a **YouTube channel**:
   enable YouTube Data API v3, set up the OAuth consent screen (External, add
   yourself as a test user), then create an OAuth client of type *Web
   application*. Its redirect URI is
   `https://<your-render-name>.onrender.com/api/oauth/youtube/callback`.
3. **Render** (render.com), free plan: create a Blueprint from
   `infrastructure/render/render.free.yaml` and fill in its secrets.
4. **Whop** (whop.com): join a clipping campaign or bounty that gives you
   footage to clip. That's the money source. Add it on the dashboard's Paid
   campaigns page, footage links included.

Then:

5. On your computer, run `python scripts/gen_secrets.py` and
   `python scripts/hash_password.py`.
6. In GitHub, go to the repo → Settings → Secrets and variables → Actions, and
   add `DATABASE_URL`, `CREDENTIALS_KEY`, `GOOGLE_CLIENT_ID`,
   `GOOGLE_CLIENT_SECRET` and `PUBLIC_API_URL`. `CREDENTIALS_KEY` must match the
   value on Render.
7. Open the dashboard. Go to Social accounts → **Connect YouTube** → **Allow
   publishing**, then press **START AUTOPILOT**.
8. To skip waiting for the next 3-hour slot, go to GitHub → Actions →
   "Autopilot (free tier)" → **Run workflow**.

Facebook Reels (a Meta app plus your Page) and the Whop API token for automatic
bounty submission are optional extras you can add the same way.

## Running the dashboard on your own computer instead of Render

```
export DATABASE_URL=<Neon URL> CREDENTIALS_KEY=... SECRET_KEY=... ADMIN_PASSWORD_HASH=...
export PUBLIC_API_URL=http://localhost:8000 WEB_ORIGIN=http://localhost:8000 APP_ENV=development
cd apps/web && NEXT_OUTPUT=export NEXT_PUBLIC_API_URL="" npm run build && cd ../..
WEB_DIST=apps/web/out uvicorn vp_api.app:app --port 8000
```

Use `http://localhost:8000/api/oauth/youtube/callback` as the Google redirect
URI. You only need the computer on while you use the dashboard. Publishing
still runs on GitHub.
