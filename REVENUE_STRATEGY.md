# Revenue strategy

_Researched 2026-11-25. Rates and rules change often; the system re-reads live
campaign data rather than relying on the numbers below. Nothing here is a
forecast or a promise._

## What actually pays clippers today

| Stream | How money flows | Typical rate (snapshot) | Can the system automate it? |
|---|---|---|---|
| **Whop bounties (clipping type)** | Poster funds a bounty; each accepted submission earns a flat `gross_reward_amount`. | Varies per bounty | **Yes, via the official Whop API (beta):** `GET /bounties?status=open&business_goal_type=clipping` lists bounties the signed-in user can work, and `POST /bounty_submissions` submits a post URL. Needs a Whop OAuth app and your Whop sign-in. Approve/deny is done by people at the poster. |
| **Content Rewards** (CPM campaigns, payouts via Whop) | Brand sets $ per 1,000 verified views, a minimum payout per video, and a max per video. Post the clip on your account, then submit the link. | Featured CPM campaigns about $1–$3 per 1,000 views; some music campaigns about $0.30. 10% creator fee on most campaigns. Payout rounds roughly every 10 days. | **Partly.** No public clipper API found, so discovery and link submission are **manual** (you paste a campaign in once; the system produces and publishes the clips and lists the ready-to-submit links). |
| **Vyro** (Beast Industries) | Brand-funded campaigns, pay per 1,000 verified views, link submission. | Featured campaigns about $1.40–$2.00 per 1,000 views. Weekly withdrawals from $10. | **Partly**, same as Content Rewards: no public API found. |
| **Direct creator deals** | A podcaster or streamer pays a retainer or per-clip fee and supplies footage. | Negotiated | Footage intake, clipping, publishing and reporting are automated. Outreach drafts are generated, but **you send them and you sign any contract.** |
| **YouTube Partner Program (Shorts revenue share)** | Ad revenue pool shared by Shorts views once the channel is in YPP. | Low per view; depends on audience | Publishing yes (YouTube Data API). Revenue reporting via YouTube Analytics API. Reused-content rules apply (below). |
| **Facebook Content Monetization** | Pays for eligible Reels and posts by qualified views. | Shown in-app as "earnings rate" per 1,000 qualified views | Invite-only (express interest in Professional Dashboard). Publishing yes after Meta App Review. Meta says it increasingly rewards **original** creators. |
| **Affiliate links** | Commission on sales from links in descriptions. | Program-specific | Links and required disclosures can be added automatically to relevant videos; payouts are reported by the affiliate network. |

## Rules that shape the design

- **Clips must be transformed, not reuploaded.** YouTube excludes "reuploads of other creators' content" and "compilations with no original content added" from Shorts revenue sharing. The editor adds captions, reframing, cuts, and hooks, but monetisation of clipped content on YouTube/Facebook is never assumed; it's tracked from real data.
- **Campaign money is the most direct path.** For campaign clips the creator has authorised the footage, so rights are clean, and the payout doesn't depend on YPP or Facebook monetisation eligibility.
- **Verified views only.** Campaign platforms verify views through platform APIs and run bot checks. The system never buys or manufactures engagement.
- **Estimates are separate from money.** Expected value is calculated to choose campaigns, stored as an estimate, and shown labelled. Revenue counts as *confirmed* only with evidence (a payout record or an API-reported credited amount).

## How the system chooses work

For each eligible campaign, before producing anything:

```
expected payout per clip = E[ min(rate × qualified_views / 1000, max_per_video) if ≥ min_payout else 0 ]   (CPM)
                         or flat reward                                                                   (flat)
risk-adjusted value     = payout × P(approval) × P(payment) × (1 − platform fee)
expected profit         = risk-adjusted value − production cost per clip
```

- `qualified_views` comes from **our own published clips** on that platform once we have them; until then a deliberately conservative prior (median 300 views, wide spread) is used and labelled as such.
- `P(approval)` and `P(payment)` start at 0.5 / 0.8 and are replaced by observed rates per campaign source as results come in.
- Campaigns that are expired, out of budget, require a platform we can't publish to, have no usable footage, look suspicious (implausible rates, missing requirements), or have expected profit ≤ 0 are rejected with the reason recorded.

## Milestones toward $100,000/month

The dashboard's milestone table is calculated from **actual** effective payout per 1,000 views, views per video and cost per video as soon as there are at least 10 paid videos. Until then it uses the assumptions below and is labelled "assumption-based". With an effective $1.50 per 1,000 qualified views after fees:

| Monthly gross | Qualified views/month | Videos/month at 20k views each | Notes |
|---|---|---|---|
| $1 (first dollar) | ~700 | 1 | |
| $100 | ~67k | ~4 | |
| $1,000 | ~0.7M | ~34 | ~1 video/day |
| $5,000 | ~3.3M | ~167 | ~5/day; several channels |
| $10,000 | ~6.7M | ~334 | needs ~$7k+/month of available campaign budget |
| $25,000 | ~17M | ~834 | ~28/day across many channels; likely needs direct deals |
| $50,000 | ~33M | ~1,667 | |
| $100,000 | ~67M | ~3,334 | ~110 videos/day; realistically requires direct contracts and a team-scale campaign pipeline |

The jump from hundreds to tens of thousands per month depends far more on average views per clip and on access to campaign budget than on production volume. The scaling engine therefore increases output only when real revenue per video exceeds real cost per video, within the limits you set.

## Sources

- [Whop Bounties API: list bounties](https://docs.whop.com/api-reference/beta/bounties/list-bounties) · [submit a bounty submission](https://docs.whop.com/api-reference/beta/bounty-submissions/submit-bounty-submission) · [run a bounty program](https://docs.whop.com/developer/bounties/run-a-bounty-program)
- [Whop docs: Content Rewards](https://docs.whop.com/memberships-and-access/third-party-apps/content-rewards)
- [Whop clipping guide (sprites.ai)](https://www.sprites.ai/blog/whop-clipping-guide)
- [Vyro vs Whop Content Rewards (OpusClip, vendor blog)](https://www.opus.pro/blog/vyro-vs-whop)
- [YouTube Shorts monetization policies](https://support.google.com/youtube/answer/12504220?hl=en)
- [Meta: Creator Fast Track and Content Monetization updates](https://about.fb.com/news/2026/03/creator-fast-track-grow-your-audience-earn-money-on-facebook/)
