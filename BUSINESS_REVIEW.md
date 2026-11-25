# Business review from five perspectives

_A structured critique of ViralPilot as a revenue business, written before
any real revenue exists. Each view gives a verdict and what would change it._

## 1. The investor: "Where does the first $1,000 come from?"

- **Verdict: plausible, unproven.** Paid clipping campaigns (Whop bounties,
  Content Rewards, Vyro) pay per verified view or per accepted clip, and
  footage comes authorised, so the path to the first dollars doesn't depend on
  YouTube or Facebook monetisation eligibility.
- At an effective ~$1.50 per 1,000 qualified views, $1,000/month needs about
  700k qualified views/month. At 3–5 videos/day that's roughly 5–8k views per
  video, which new channels often don't reach for weeks.
- **What would change it:** the first 30 days of real per-clip views. The
  milestone table switches from assumptions to measured numbers after 10 paid
  videos.

## 2. The CFO: "Can it lose money?"

- **Verdict: downside is capped.** Hosting is about $33.50/month fixed. AI
  spend is about $0.03 per video and hard-capped at $3/day, $90/month and $100
  lifetime, reserved before each call. No ads, no paid boosting, no purchases.
- Worst realistic case for the first three months: about $120 in hosting plus
  under $15 of AI spend, with $0 revenue.
- Revenue counts only with evidence (payout record or API-reported credit), so
  the dashboard can't overstate results.
- **Watch:** campaign payouts arrive in rounds (about 10 days on Content
  Rewards), so cash lags views. Pending and confirmed are shown separately.

## 3. The platform-policy lawyer: "Will the accounts survive?"

- **Verdict: designed to comply; risk remains.** Official APIs only, OAuth
  consent, no account farming, no engagement buying, no scraping of campaign
  sites. Footage must be owned, licensed or campaign-authorised. Campaign clips
  carry `#ad`, "Paid partnership with …" and YouTube's paid-placement flag.
- **Residual risks:** YouTube's reused-content policy can deny Partner
  Program revenue to clip channels, even with editing. Meta's branded-content
  tag needs the sponsor's approval and isn't set by the API. Campaign rules
  vary; the engine stores each campaign's requirements and passes them to the
  copywriter, but a person should read new campaign terms once.
- **What would change it:** a strike or rejection. Account health pauses
  publishing for that account automatically.

## 4. The growth operator: "Will the clips get views?"

- **Verdict: the weakest link today.** Clip choice is deterministic and
  explainable (hook strength, pacing, keywords, sentence boundaries), the edit
  adds captions, punch-ins and loudness normalisation, and hooks come from
  Claude. Nothing has been tested against a real audience yet.
- Missing for growth: A/B testing of hooks, posting-time optimisation from
  real data, trend-aware topic selection, and original faceless content (the
  `generate.original` stage is still blocked).
- **What would change it:** per-clip retention and view data from the
  metrics collector (1 h / 24 h / 72 h / 7 d / 30 d), fed back into clip-scoring
  weights. That's the next build step once real posts exist.

## 5. The SRE: "Does it really run 24/7 without you?"

- **Verdict: yes, within its limits.** One service runs API, dashboard,
  worker and scheduler. Jobs live in Postgres with leases, retries,
  dead-letter and blocked states; blocked jobs re-check every 30 minutes and
  clear their dashboard warning when they succeed. Every external call is
  idempotent or checked before retry (YouTube tag lookup, Facebook step state).
- **Needs you:** weekly YouTube reconnects until Google verifies the OAuth
  app, Meta App Review only if you add other people's Pages, and occasional
  manual submission for campaigns without an API.
- **Single points of failure:** one worker process (concurrency 1) and one
  disk. Fine at 3–5 videos/day; scale-out uses `render.split.yaml` plus
  object storage.

## Overall

Build quality and safety are ahead of business proof. The fastest way to
learn whether this makes money is to connect one YouTube channel and one
Facebook Page, join two or three paid campaigns with authorised footage, and
let it run for 30 days at the default caps. Expected cost of that test: about
$40.
