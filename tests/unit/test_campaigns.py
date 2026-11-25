from datetime import timedelta

import pytest
from vp_agents import campaigns as cmp
from vp_agents.worker import run_job
from vp_analytics import profit, scaling
from vp_shared import db, jobs
from vp_shared.models import (
    CampaignStatus,
    CampaignSubmission,
    Clip,
    ContentItem,
    Job,
    Publication,
    PublicationStatus,
    RevenueEntry,
    SocialAccount,
    Source,
    SubmissionStatus,
)

from tests.conftest import start_autopilot


def cd(**kw):
    base = dict(provider="content_rewards", external_id="c1", name="Podcast clips", url="https://example.com/c1",
                payout_model="cpm", rate_per_1k=2.0, min_payout=1.0, max_payout_per_video=200.0,
                budget_total=1000.0, budget_remaining=800.0, platform_fee_pct=0.10,
                platforms=["youtube"], requirements="Post a 30-60s clip with captions.",
                footage_urls=["https://cdn.example.com/ep1.mp4"])
    base.update(kw)
    return cmp.CampaignData(**base)


# ---------------------------------------------------------------- profit model

def test_cpm_expectation_respects_floor_and_cap():
    vm = profit.ViewModel(1000, 1.0, "test")
    lo = profit.evaluate(payout_model="cpm", rate_per_1k=2, flat_reward=None, min_payout=0, max_payout_per_video=None,
                         budget_remaining=None, fee_pct=0, views=vm, p_approval=1, p_payment=1, cost_per_clip=0)
    floored = profit.evaluate(payout_model="cpm", rate_per_1k=2, flat_reward=None, min_payout=5,
                              max_payout_per_video=None, budget_remaining=None, fee_pct=0, views=vm,
                              p_approval=1, p_payment=1, cost_per_clip=0)
    capped = profit.evaluate(payout_model="cpm", rate_per_1k=2, flat_reward=None, min_payout=0,
                             max_payout_per_video=1.0, budget_remaining=None, fee_pct=0, views=vm,
                             p_approval=1, p_payment=1, cost_per_clip=0)
    assert floored.expected_payout < lo.expected_payout and floored.p_reach_min < 1
    assert capped.expected_payout <= 1.0
    assert lo.label == "estimate"


def test_priors_are_disclosed():
    ev = profit.evaluate(payout_model="flat", rate_per_1k=None, flat_reward=10, min_payout=None,
                         max_payout_per_video=None, budget_remaining=100, fee_pct=0.1, views=profit.view_model([]))
    assert any("prior" in a for a in ev.assumptions) and ev.clips_affordable == 10
    assert ev.expected_profit == pytest.approx(10 * 0.5 * 0.8 * 0.9 - 0.15, abs=1e-3)


def test_view_model_uses_history_when_available():
    assert profit.view_model([10, 20]).source == "prior"
    vm = profit.view_model([100, 200, 400, 800, 1600, 3200])
    assert vm.source.startswith("history") and 400 <= vm.median <= 800


# ---------------------------------------------------------------- eligibility

@pytest.fixture
def yt_account():
    with db.session_scope() as s:
        s.add(SocialAccount(platform="youtube", display_name="ch", publishing_allowed=True))


@pytest.fixture
def yt_available(monkeypatch):
    import vp_publishing

    class Ok(vp_publishing.Publisher):
        platform = "youtube"

        def availability(self, a):
            return vp_publishing.Availability(True)

    monkeypatch.setitem(vp_publishing.REGISTRY, "youtube", Ok())


@pytest.mark.parametrize("kw,status,needle", [
    (dict(ends_at=jobs.now_utc() - timedelta(days=1)), CampaignStatus.ended, "end date"),
    (dict(budget_remaining=0.5), CampaignStatus.exhausted, "budget"),
    (dict(rate_per_1k=80), CampaignStatus.rejected, "implausible"),
    (dict(requirements=""), CampaignStatus.rejected, "written requirements"),
    (dict(automation_allowed=False), CampaignStatus.rejected, "forbids"),
    (dict(platforms=["x"]), CampaignStatus.rejected, "platforms"),
    (dict(rate_per_1k=0.05), CampaignStatus.rejected, "unprofitable"),
    (dict(footage_urls=[]), CampaignStatus.restricted, "footage"),
])
def test_assess_rejections(kw, status, needle, yt_account, yt_available):
    with db.session_scope() as s:
        c = cmp.upsert(s, cd(**kw))
        cmp.assess(s, c)
        assert c.status == status and needle in c.status_reason


def test_geo_restriction(monkeypatch, yt_account, yt_available):
    monkeypatch.setenv("OPERATOR_COUNTRY", "US")
    with db.session_scope() as s:
        c = cmp.upsert(s, cd(countries=["GB"]))
        cmp.assess(s, c)
        assert c.status == CampaignStatus.rejected


def test_no_publishable_account_is_restricted_not_rejected():
    with db.session_scope() as s:
        c = cmp.upsert(s, cd())
        cmp.assess(s, c)
        assert c.status == CampaignStatus.restricted and "no connected account" in c.status_reason


def test_eligible_campaign_ranked_and_activated(yt_account, yt_available):
    with db.session_scope() as s:
        good = cmp.upsert(s, cd(external_id="good", rate_per_1k=3.0))
        ok = cmp.upsert(s, cd(external_id="ok", rate_per_1k=1.0))
        for c in (good, ok):
            cmp.assess(s, c)
        ranked = cmp.rank(s)
        assert [c.external_id for c in ranked][:2] == ["good", "ok"]
        assert good.evaluation["label"] == "estimate"
        assert cmp.activate(s, good) == 1
        src = s.query(Source).filter_by(campaign_id=good.id).one()
        assert src.license_type.value == "creator_authorized" and src.kind.value == "direct_file"
        assert good.status == CampaignStatus.active


# ---------------------------------------------------------------- whop adapter

def test_whop_mapping(monkeypatch):
    monkeypatch.setenv("WHOP_ACCESS_TOKEN", "t")
    a = cmp.WhopBountyAdapter()
    monkeypatch.setattr(a, "_get", lambda path, params: {"data": [{
        "id": "bnty_1", "title": "Clip our podcast", "status": "open", "currency": "usd",
        "gross_reward_amount": 25, "net_reward_amount": 22.5, "budget_amount": 500, "gross_paid_out_amount": 100,
        "allowed_country_codes": [], "description": "Post on YouTube Shorts or TikTok. Footage: https://cdn.x.com/ep.mp4",
        "poster": {"name": "Pod Co"}}]})
    [d] = a.discover()
    assert d.payout_model == "flat" and d.flat_reward == 22.5 and d.budget_remaining == 400
    assert d.platforms == ["tiktok", "youtube"] and d.footage_urls == ["https://cdn.x.com/ep.mp4"]
    assert d.submission_method == "api"


def test_discover_stage_without_sources_raises_blocker():
    from vp_shared.models import IntegrationBlocker

    start_autopilot()
    with db.session_scope() as s:
        jid = jobs.enqueue(s, "discover.campaigns", "dc").id
    assert run_job(jid) == "succeeded"
    with db.session_scope() as s:
        assert s.query(IntegrationBlocker).filter_by(key="campaigns.no_sources").one()


# ------------------------------------------------------- submissions & money

def _published_campaign_clip(s, campaign, url="https://youtube.com/shorts/abc"):
    acc = SocialAccount(platform="youtube", display_name="ch", publishing_allowed=True)
    item = ContentItem(fingerprint="f", campaign_id=campaign.id)
    s.add_all([acc, item])
    s.flush()
    clip = Clip(item_id=item.id, campaign_id=campaign.id, start_s=0, end_s=30)
    s.add(clip)
    s.flush()
    pub = Publication(clip_id=clip.id, account_id=acc.id, platform="youtube", idempotency_key=f"k{clip.id}",
                      status=PublicationStatus.published, platform_post_id="abc", platform_url=url,
                      campaign_id=campaign.id)
    s.add(pub)
    s.flush()
    return pub


def test_manual_campaign_submission_is_flagged_not_faked():
    start_autopilot()
    with db.session_scope() as s:
        c = cmp.upsert(s, cd())
        pub = _published_campaign_clip(s, c)
        cmp.create_submission(s, pub, c.id)
        jid = s.query(Job).filter_by(kind="submit.campaign").one().id
    assert run_job(jid) == "succeeded"
    with db.session_scope() as s:
        sub = s.query(CampaignSubmission).one()
        assert sub.status == SubmissionStatus.manual_required and sub.post_url.endswith("/abc")
        assert s.query(RevenueEntry).count() == 0


def test_whop_api_submission_and_pending_revenue(monkeypatch):
    monkeypatch.setenv("WHOP_ACCESS_TOKEN", "t")
    a = cmp.adapter_for("whop_bounty")
    calls = []
    monkeypatch.setattr(a, "submit", lambda bid, url, caption="": calls.append((bid, url)) or {"id": "bsub_9"})
    monkeypatch.setattr(a, "submission_status", lambda sid: {"id": sid, "status": "approved"})
    start_autopilot()
    with db.session_scope() as s:
        c = cmp.upsert(s, cd(provider="whop_bounty", external_id="bnty_1", payout_model="flat", flat_reward=20,
                             rate_per_1k=None, submission_method="api"))
        pub = _published_campaign_clip(s, c)
        cmp.create_submission(s, pub, c.id)
        jid = s.query(Job).filter_by(kind="submit.campaign").one().id
    run_job(jid)
    assert calls == [("bnty_1", "https://youtube.com/shorts/abc")]
    with db.session_scope() as s:
        pj = s.query(Job).filter_by(kind="poll.submission").one().id
    run_job(pj)
    with db.session_scope() as s:
        r = s.query(RevenueEntry).one()
        assert r.status.value == "pending" and r.amount == 20 and "bsub_9" in r.evidence
        assert s.query(CampaignSubmission).one().status == SubmissionStatus.approved


# ---------------------------------------------------------------- scaling

def _si(**kw):
    base = dict(current_per_day=3, ceiling=5, floor=1, videos_14d=40, paid_videos_14d=10,
                confirmed_revenue_14d=50, pending_revenue_14d=0, cost_14d=10, unhealthy_accounts=0)
    base.update(kw)
    return scaling.ScalingInput(**base)


def test_scaling_rules():
    assert scaling.decide(_si()).new_per_day == 4
    assert scaling.decide(_si(current_per_day=5)).new_per_day == 5  # ceiling
    assert scaling.decide(_si(videos_14d=5)).action == "hold"
    assert scaling.decide(_si(confirmed_revenue_14d=0, cost_14d=8)).new_per_day == 2
    assert scaling.decide(_si(unhealthy_accounts=1)).action == "reduce"
    # pending money alone never justifies growth
    assert scaling.decide(_si(confirmed_revenue_14d=0, pending_revenue_14d=500)).action == "hold"
