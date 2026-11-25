# Campaign feed format

`CAMPAIGN_FEED_URLS` lets the worker read paid clipping campaigns from any
**authorized** JSON feed, for example a feed a brand or agency gives you, or one
you host yourself. ViralPilot never scrapes campaign marketplaces. If a platform
has no API and no feed, add its campaigns by hand on the **Paid campaigns** page.

Each URL must be `https://` and resolve to a public IP (the SSRF guard rejects
anything else). The body is either a JSON array of campaigns or
`{"campaigns": [...]}`.

## Fields

| Field | Required | Type | Notes |
|---|---|---|---|
| `external_id` | yes | string | Unique per provider. Used for upserts. |
| `name` | yes | string | |
| `provider` | no | string | Defaults to `feed`. |
| `creator` | no | string | Brand or creator running the campaign. |
| `url` | no | string | Campaign page, opened from the dashboard. |
| `payout_model` | no | `cpm` or `flat` | Default `cpm`. |
| `currency` | no | string | Default `USD`. |
| `rate_per_1k` | for cpm | number | Payout per 1,000 qualified views. |
| `flat_reward` | for flat | number | Payout per accepted submission. |
| `budget_total`, `budget_remaining` | no | number | Exhausted campaigns are skipped. |
| `min_payout` | no | number | Views below this threshold earn nothing. |
| `max_payout_per_video` | no | number | Caps expected value per clip. |
| `platform_fee_pct` | no | number 0–1 | e.g. `0.10` for a 10% marketplace fee. |
| `ends_at` | no | ISO 8601 | Ended campaigns are skipped. |
| `platforms` | no | string[] | `youtube`, `facebook`, `tiktok`, `instagram`. Empty means any. |
| `countries` | no | string[] | ISO codes. Checked against `OPERATOR_COUNTRY`. |
| `requirements` | no | string | Shown to you and used for QC notes. |
| `footage_urls` | no | string[] | Footage the campaign owner authorizes you to clip. Becomes a `creator_authorized` source. |
| `rights_note` | no | string | Where the authorization comes from. |
| `submission_method` | no | `api` or `manual` | `manual` puts the clip in your submission queue. |
| `automation_allowed` | no | bool | `false` blocks automated submission. |

## Example

```json
{
  "campaigns": [
    {
      "external_id": "acme-spring-2026",
      "name": "Acme podcast clips",
      "creator": "Acme",
      "payout_model": "cpm",
      "rate_per_1k": 1.5,
      "budget_remaining": 2000,
      "platform_fee_pct": 0.1,
      "ends_at": "2026-12-31T23:59:59+00:00",
      "platforms": ["youtube", "facebook"],
      "footage_urls": ["https://cdn.example.com/acme/ep12.mp4"],
      "rights_note": "Clipping licence in the Acme campaign brief",
      "submission_method": "manual"
    }
  ]
}
```

Ranking numbers derived from a feed are **estimates** until real metrics and
confirmed payouts replace them.
