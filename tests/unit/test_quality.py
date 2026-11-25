"""QC on real rendered files, metadata writers, and the non-optional rules."""
import shutil
from types import SimpleNamespace

import pytest
from vp_agents import metadata as md
from vp_agents.stages import quality
from vp_shared import budget, db
from vp_shared.models import Clip, ClipStage, ContentItem, CostEntry, ItemStage, LicenseType
from vp_video import ffmpeg, qc

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def _make(path, *, size="1080x1920", src="testsrc2", audio="sine=frequency=300", dur=12):
    ffmpeg.run(["-y", "-f", "lavfi", "-i", f"{src}{'' if src.endswith(':') else '='}size={size}:rate=30:duration={dur}",
                "-f", "lavfi", "-i", f"{audio}:duration={dur}", "-shortest", "-af", "loudnorm=I=-14",
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(path)])
    return str(path)


@needs_ffmpeg
def test_qc_passes_a_correct_render(tmp_path):
    rep = qc.check(_make(tmp_path / "ok.mp4"), caption_words=40)
    assert rep.passed, [c for c in rep.failures]
    assert {c.name for c in rep.checks} >= {"resolution", "loudness", "black_frames", "frozen_video", "dead_air"}


@needs_ffmpeg
def test_qc_wrong_resolution_is_retryable(tmp_path):
    rep = qc.check(_make(tmp_path / "wide.mp4", size="1280x720"), caption_words=40)
    assert not rep.passed and [c.name for c in rep.failures] == ["resolution"] and rep.retryable


@needs_ffmpeg
def test_qc_black_silent_clip_is_discarded_not_retried(tmp_path):
    p = _make(tmp_path / "black.mp4", src="color=c=black:", audio="anullsrc=r=48000:cl=stereo")
    rep = qc.check(p, caption_words=0)
    names = {c.name for c in rep.failures}
    assert {"black_frames", "captions"} <= names and not rep.retryable


def test_qc_missing_file():
    rep = qc.check("/nonexistent.mp4", caption_words=10)
    assert not rep.passed and rep.retryable


# ----------------------------------------------------------------- metadata

TRANSCRIPT = ("Have you ever wondered why most startups fail in the first year? "
              "The answer is cash flow. Founders spend on growth before revenue is steady.")


def test_rules_writer_uses_only_the_transcript():
    m = md.rules(md.MetaInput(transcript=TRANSCRIPT, niche="business"))
    assert m.hook.startswith("Have you ever wondered") and m.writer == "rules"
    assert "#business" in m.hashtags and any(t in m.hashtags for t in ("#startups", "#founders", "#cash"))


def test_enforce_adds_disclosure_attribution_and_shorts_tag():
    mi = md.MetaInput(transcript=TRANSCRIPT, license_type="cc_by", attribution="Jane Doe, CC BY 4.0",
                      campaign_name="Acme clips", campaign_creator="Acme", platforms=["youtube"])
    meta = md.enforce(md.Metadata(hook="Like and subscribe to win! Cash flow", title="x" * 150,
                                  description="Why startups fail", hashtags=["startups", "#Startups", "bad tag!"]),
                      mi)
    assert "like and subscribe" not in meta.hook.lower()
    assert len(meta.title) <= md.TITLE_MAX
    assert meta.paid_promotion and "Paid partnership with Acme." in meta.description
    assert "Credit: Jane Doe, CC BY 4.0" in meta.description
    assert meta.hashtags[:2] == ["#ad", "#Shorts"] and meta.hashtags.count("#startups") == 1


def test_enforce_refuses_cc_by_without_attribution():
    with pytest.raises(ValueError):
        md.enforce(md.rules(md.MetaInput(transcript=TRANSCRIPT)), md.MetaInput(transcript=TRANSCRIPT,
                                                                               license_type="cc_by_sa"))


class FakeClient:
    def __init__(self, text='{"hook":"Why startups fail","title":"Cash flow kills startups",'
                            '"description":"One reason.","hashtags":["startups"]}', stop="end_turn"):
        self.calls = []
        resp = SimpleNamespace(stop_reason=stop, model="claude-opus-5-5",
                               usage=SimpleNamespace(input_tokens=900, output_tokens=120),
                               content=[SimpleNamespace(type="text", text=text)])

        def create(**kw):
            self.calls.append(kw)
            return resp

        self.messages = SimpleNamespace(create=create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))


@pytest.fixture
def claude_on(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    fake = FakeClient()
    md.set_client(fake)
    yield fake
    md.set_client(None)


def _clip(s):
    item = ContentItem(fingerprint="f", title="ep", license_type=LicenseType.user_owned, stage=ItemStage.clipped)
    s.add(item)
    s.flush()
    c = Clip(item_id=item.id, start_s=0, end_s=30, stage=ClipStage.qc_passed, transcript_text=TRANSCRIPT)
    s.add(c)
    s.flush()
    return c


def test_claude_writer_records_real_cost(claude_on):
    with db.session_scope() as s:
        clip = _clip(s)
        meta = quality.write_metadata(s, clip, md.MetaInput(transcript=TRANSCRIPT, platforms=["youtube"]))
        assert meta.writer == "claude" and meta.title == "Cash flow kills startups"
        entry = s.query(CostEntry).one()
        assert entry.category == "llm.metadata" and entry.status.value == "committed"
        assert entry.amount_usd == pytest.approx(md.cost_of("claude-opus-5-5", 900, 120))
        assert entry.amount_usd < 0.05
    call = claude_on.calls[0]
    assert call["output_config"]["format"]["type"] == "json_schema" and call["fallbacks"] == "default"


def test_refusal_falls_back_to_rules_and_still_bills(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    md.set_client(FakeClient(text="", stop="refusal"))
    try:
        with db.session_scope() as s:
            meta = quality.write_metadata(s, _clip(s), md.MetaInput(transcript=TRANSCRIPT))
            assert meta.writer == "rules" and any("declined" in n for n in meta.notes)
            assert s.query(CostEntry).one().amount_usd > 0
    finally:
        md.set_client(None)


def test_budget_exhausted_uses_rules_without_calling_model(claude_on):
    with db.session_scope() as s:
        b = budget.get_budget(s)
        b.daily_limit_usd = 0.0
        meta = quality.write_metadata(s, _clip(s), md.MetaInput(transcript=TRANSCRIPT))
        assert meta.writer == "rules" and any("budget" in n for n in meta.notes)
    assert claude_on.calls == []


def test_no_key_uses_rules(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with db.session_scope() as s:
        meta = quality.write_metadata(s, _clip(s), md.MetaInput(transcript=TRANSCRIPT))
        assert meta.writer == "rules" and s.query(CostEntry).count() == 0


def test_estimate_covers_actual():
    mi = md.MetaInput(transcript=TRANSCRIPT * 20)
    assert md.estimate_usd(mi) >= md.cost_of(md.DEFAULT_MODEL, 900, 120)
    assert md.estimate_usd(mi) < 0.10  # fits well inside the $0.50 per-video cap
