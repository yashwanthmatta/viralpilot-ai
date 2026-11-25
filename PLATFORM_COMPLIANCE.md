# Platform approvals and limits

These are requirements set by each platform. The code does not try to get
around any of them. Verify the current rules when you apply: platforms change
them, and this summary is not legal advice.

| Platform | What's needed for unattended publishing | Practical impact |
|---|---|---|
| **YouTube Shorts** | A Google Cloud project with the YouTube Data API v3 and an OAuth client. `youtube.upload` is a sensitive scope: while the OAuth consent screen is in *Testing*, refresh tokens expire after 7 days (reconnect weekly) until Google verifies the app. YouTube's `videos.insert` page (checked 2026-11-25) says uploads from unverified API projects are no longer restricted to private, and that uploads cost 1 unit from a separate Video Uploads bucket with 100 calls/day. | **Integrated** (OAuth, resumable upload, duplicate check, metrics). Needs your Google Cloud OAuth client. |
| **TikTok** | TikTok for Developers app with the Content Posting API (Direct Post) approved through TikTok's audit. Unaudited apps can only post with private visibility. TikTok's sharing guidelines require showing the creator's info and letting them choose privacy settings and confirm, which may conflict with fully unattended posting. | Likely blocked for unattended public posting. Alternative TikTok allows: upload as a draft to the creator's inbox and finish in the app. |
| **Instagram Reels** | Instagram professional (Business or Creator) account linked to a Facebook Page, a Meta app, and App Review approval for content-publishing permissions. API-published posts are capped per rolling 24 hours. | Possible after Meta App Review (needs a screencast, privacy policy URL, and business verification for some permissions). |
| **Facebook Reels** | A Facebook Page you manage, a Meta app, and App Review approval for Page publishing permissions. | Same review process as Instagram; can be requested together. |

Until a platform's adapter is integrated and connected, it reports itself as blocked, the
dashboard shows why, and publications to it are marked `blocked` while other
platforms continue.

## Content rights

The system will only process:

- content you created (`user_owned`), with a statement of ownership;
- content with written permission from the creator (`creator_authorized`), with a reference to that permission;
- CC BY or CC BY-SA content with attribution recorded (and BY-SA's share-alike terms on the output);
- CC0 and public-domain content;
- stock/library content under a commercial licence you hold.

Publicly viewable is not the same as licensed: YouTube videos, podcasts and
interviews without one of the above are rejected. Music is the same: only
licensed or royalty-free tracks you are entitled to use.

## Paid clipping campaigns

| Program | Integration | Notes |
|---|---|---|
| **Whop bounties** | Official Whop API (`GET /bounties`, `POST /bounty_submissions`) with your own OAuth token | Beta API. Flat reward per accepted submission. Submissions are created only for clips the platform confirmed as published. |
| **Whop Content Rewards** | Manual | No public API for clippers. CPM roughly $1–3, about 10% fee, payouts in rounds. Follow each campaign's rules on footage and disclosure. |
| **Vyro** | Manual | No public API. Roughly $1.40–2.00 per 1,000 views. |
| **Direct brand deals** | Manual or authorized feed | Written agreement required before clipping. ViralPilot never sends outreach or accepts terms on your behalf. |

Rules the engine applies to every campaign: footage must come from the
campaign owner (stored as a creator-authorized source), clips go only to
platforms where you have an approved, healthy account, ads/sponsorship
disclosures are kept, and nothing buys or manufactures views.
Campaign marketplaces are never scraped.

## Monetization eligibility notes

- YouTube's Partner Program excludes reused content without significant
  original contribution, so clip channels rely on campaign payouts first.
- Facebook Content Monetization is invite-only.

### Disclosures the YouTube adapter sends

- `paidProductPlacementDetails.hasPaidProductPlacement = true` for every campaign clip, plus "Paid partnership with …" and `#ad` in the description.
- `selfDeclaredMadeForKids = false`; `containsSyntheticMedia` is set for generated (faceless) videos.
