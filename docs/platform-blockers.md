# Platform approvals and limits

These are requirements set by each platform. The code does not try to get
around any of them. Verify the current rules when you apply: platforms change
them, and this summary is not legal advice.

| Platform | What's needed for unattended publishing | Practical impact |
|---|---|---|
| **YouTube Shorts** | A Google Cloud project with the YouTube Data API v3 and OAuth consent screen. Uploads from unverified/unaudited API projects are locked to **private** until the project passes YouTube's API compliance audit. Default quota is 10,000 units/day; an upload costs about 1,600, so roughly 6 uploads/day before a quota increase. | Most promising first target. Publishing works for testing right away (as private); public posts after the audit. |
| **TikTok** | TikTok for Developers app with the Content Posting API (Direct Post) approved through TikTok's audit. Unaudited apps can only post with private visibility. TikTok's sharing guidelines require showing the creator's info and letting them choose privacy settings and confirm, which may conflict with fully unattended posting. | Likely blocked for unattended public posting. Alternative TikTok allows: upload as a draft to the creator's inbox and finish in the app. |
| **Instagram Reels** | Instagram professional (Business or Creator) account linked to a Facebook Page, a Meta app, and App Review approval for content-publishing permissions. API-published posts are capped per rolling 24 hours. | Possible after Meta App Review (needs a screencast, privacy policy URL, and business verification for some permissions). |
| **Facebook Reels** | A Facebook Page you manage, a Meta app, and App Review approval for Page publishing permissions. | Same review process as Instagram; can be requested together. |

Until approval, the adapter for each platform reports itself as blocked, the
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
