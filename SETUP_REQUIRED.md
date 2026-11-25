# Setup that needs you

Only things the system genuinely cannot do for you. Everything else is automated.

## Now (to run it in the cloud)

1. **Approve hosting spend.** Nothing has been deployed or purchased. The
   recommended setup is one Render service running everything, about
   **$33.50/month** fixed plus about $0.03 of AI per video. Details and the
   trade-offs are in [DEPLOYMENT.md](DEPLOYMENT.md).
2. **Create the secrets** (on your machine, never in git):
   `python scripts/gen_secrets.py` and `python scripts/hash_password.py`, then
   enter them as secret env vars on the host.
3. **Turn on branch protection** for `main` in GitHub (Settings → Branches),
   requiring the CI check. This session doesn't have admin rights to do it.

## Before content can flow

4. **Authorise at least one source** in the dashboard: a feed of content you
   own, have written permission for, or that is CC BY / BY-SA / CC0 / public
   domain. You state the licence and evidence once per source.
5. **Anthropic API key** (optional) for Claude-written hooks and titles
   (`ANTHROPIC_API_KEY`). Without it the free rules writer is used. Spending is
   capped by the dashboard limits either way.
6. Storage: the Render disk (10 GB) is enough at 3–5 videos/day. Object
   storage (R2/S3) is only needed when scaling out.

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

## Before publishing

7. **YouTube:**
   1. In Google Cloud Console create a project and enable **YouTube Data API v3**.
   2. Configure the OAuth consent screen (External) and add yourself as a test user.
   3. Create an OAuth client of type **Web application** with the redirect URI
      `<PUBLIC_API_URL>/api/oauth/youtube/callback`.
   4. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `PUBLIC_API_URL` as secrets on the host.
   5. In the dashboard: Social accounts → **Connect YouTube**, then **Allow publishing**.
   6. While the consent screen is in Testing, Google expires the refresh token after 7 days;
      the dashboard will ask you to reconnect. Submit the app for Google verification to stop that.
8. **Facebook Reels:**
   1. At developers.facebook.com create an app (type Business) and add **Facebook Login**.
   2. Add the redirect URI `<PUBLIC_API_URL>/api/oauth/facebook/callback` under Facebook Login settings.
   3. Set `META_APP_ID` and `META_APP_SECRET` as secrets on the host.
   4. Dashboard: Social accounts → **Connect Facebook**, approve the Page, then **Allow publishing**.
   5. As the app's admin you can publish to your own Page right away. Meta App Review for
      `pages_manage_posts` is only needed to connect Pages of people who aren't app admins/testers.
   Instagram is not integrated yet (it needs the same Meta app plus an Instagram professional account).
9. **TikTok:** TikTok for Developers app and Content Posting API audit.

See [PLATFORM_COMPLIANCE.md](PLATFORM_COMPLIANCE.md) for what each one involves.
