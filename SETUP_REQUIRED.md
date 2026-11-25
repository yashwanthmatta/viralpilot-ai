# Setup that needs you

Only things the system genuinely cannot do for you. Everything else is automated.

## Now (to run phase 1 in the cloud)

1. **Approve hosting spend.** Nothing has been deployed or purchased. The
   suggested setup (Render for API + always-on worker + Postgres + Redis,
   Vercel Hobby for the dashboard) is estimated at roughly **$30–40/month**
   before AI usage; check current prices on render.com/pricing. Background
   workers have no free tier, and free web services sleep, so a free-only setup
   can't run 24/7. Vercel Hobby is for non-commercial use; if the channels earn
   money, Vercel's terms require the Pro plan (about $20/month) or you can host
   the dashboard on Render too.
2. **Create the secrets** (on your machine, never in git):
   `python scripts/gen_secrets.py` and `python scripts/hash_password.py`, then
   enter them as secret env vars on the host.
3. **Turn on branch protection** for `main` in GitHub (Settings → Branches),
   requiring the CI check. This session doesn't have admin rights to do it.

## Before content can flow (phase 2–3)

4. **Authorise at least one source** in the dashboard: a feed of content you
   own, have written permission for, or that is CC BY / BY-SA / CC0 / public
   domain. You state the licence and evidence once per source.
5. **API keys** for the steps that need a model: an Anthropic (Claude) key, and
   optionally OpenAI and a text-to-speech provider. Spending is capped by the
   dashboard limits regardless.
6. **Cloudflare R2 (or S3) bucket** and access keys for rendered videos.

## Paid campaigns (optional, any time)

7a. **Whop:** to discover and submit to Whop clipping bounties automatically,
    create a Whop OAuth app, authorize it on your own Whop account with the
    scopes `bounty:basic:read` and `bounty:submission:create`, and set the
    token as the secret `WHOP_ACCESS_TOKEN`. Without it, add campaigns by hand.
7b. **`OPERATOR_COUNTRY`:** the ISO code of the country you are paid in, so
    geo-restricted campaigns are skipped.
7c. **Content Rewards / Vyro:** no public clipper API. Join campaigns on their
    sites, add them on the Paid campaigns page, and submit the clips the
    dashboard queues for you.

## Before publishing (phase 4)

7. **YouTube:**
   1. In Google Cloud Console create a project and enable **YouTube Data API v3**.
   2. Configure the OAuth consent screen (External) and add yourself as a test user.
   3. Create an OAuth client of type **Web application** with the redirect URI
      `<PUBLIC_API_URL>/api/oauth/youtube/callback`.
   4. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `PUBLIC_API_URL` as secrets on the host.
   5. In the dashboard: Social accounts → **Connect YouTube**, then **Allow publishing**.
   6. While the consent screen is in Testing, Google expires the refresh token after 7 days;
      the dashboard will ask you to reconnect. Submit the app for Google verification to stop that.
8. **Instagram / Facebook:** Meta developer app, Instagram professional account
   linked to a Facebook Page, App Review for publishing permissions.
9. **TikTok:** TikTok for Developers app and Content Posting API audit.

See [PLATFORM_COMPLIANCE.md](PLATFORM_COMPLIANCE.md) for what each one involves.
