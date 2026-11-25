"""Video engine tests on synthetic media (FFmpeg-generated), no network."""
import shutil

import pytest
from vp_video import captions, clipfinder, editplan, ffmpeg, framing, render
from vp_video.transcribe import Segment, Transcript, Word

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")

SCRIPT = (
    "Why do most people fail at saving money? Here's the secret nobody tells you. "
    "When I was twenty I lost everything. Then I learned one rule. "
    "The key is to pay yourself first, because willpower never lasts. "
    "Um so basically that is it. Thanks for listening and see you next time."
)


def make_transcript(script: str = SCRIPT, wps: float = 2.8, pause_after: set[int] = frozenset({9, 25})) -> Transcript:
    t, words = 0.5, []
    for i, tok in enumerate(script.split()):
        d = 1 / wps
        words.append(Word(round(t, 3), round(t + d * 0.85, 3), tok))
        t += d + (1.5 if i in pause_after else 0.0)
    return Transcript("en", t + 1, [Segment(words[0].start, words[-1].end, script, words)])


def test_sentences_split_on_punctuation():
    s = clipfinder.sentences(make_transcript())
    assert s[0].text.endswith("money?") and len(s) >= 6


def test_find_clips_is_deterministic_and_explained():
    t = make_transcript()
    a = clipfinder.find_clips(t, min_s=6, max_s=25, target_s=15)
    b = clipfinder.find_clips(t, min_s=6, max_s=25, target_s=15)
    assert a and [(c.start, c.end, c.score) for c in a] == [(c.start, c.end, c.score) for c in b]
    best = a[0]
    assert best.text.startswith("Why do most people")  # the question hook wins
    assert "hook" in best.reason
    assert 6 <= best.duration <= 25


def test_weak_material_rejected():
    dull = " ".join(["the cat sat on the mat."] * 40)
    assert clipfinder.find_clips(make_transcript(dull), min_s=5, max_s=20, target_s=12, min_score=0.3) == []


def test_clips_do_not_overlap():
    cs = clipfinder.find_clips(make_transcript(SCRIPT * 3), min_s=6, max_s=20, target_s=12, max_clips=5)
    for i, a in enumerate(cs):
        for b in cs[i + 1:]:
            inter = max(0, min(a.end, b.end) - max(a.start, b.start))
            assert inter / min(a.duration, b.duration) <= 0.3


def test_edit_plan_removes_pauses_and_remaps_words():
    t = make_transcript()
    words = t.words()
    p = editplan.plan(words, words[0].start, words[30].end)
    assert p.removed_s > 2.0  # the two 1.5 s pauses were shortened
    assert len(p.pieces) == 3
    assert p.words[0].start < 0.2
    starts = [w.start for w in p.words]
    assert starts == sorted(starts) and p.words[-1].end <= p.duration + 1e-6
    assert any(w.keyword for w in p.words)  # "secret", "never", numbers, ...


def test_ass_captions_highlight_active_word():
    p = editplan.plan(make_transcript().words(), 0, 12)
    ass = captions.build_ass(p.words)
    assert "PlayResX: 1080" in ass and "Dialogue:" in ass
    assert ass.count("Dialogue:") == len(p.words)  # one event per spoken word
    assert "\\fscx112" in ass


def test_crop_offsets_follow_faces_and_stay_in_frame():
    offs = framing.crop_offsets([0.2, None, 0.9, 0.9], 1920, 1080)
    crop_w = int(round(1080 * 9 / 16 / 2)) * 2
    assert all(0 <= x <= 1920 - crop_w for x in offs)
    assert offs[0] < offs[2]  # moved right towards the speaker
    assert offs[1] == offs[0]  # no face: hold position


@pytest.fixture
def source(tmp_path):
    out = tmp_path / "src.mp4"
    ffmpeg.run(["-y", "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=16",
                "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=16",
                "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(out)])
    return str(out)


@needs_ffmpeg
def test_probe_and_scene_detection(source):
    info = ffmpeg.probe(source)
    assert (info.width, info.height) == (1920, 1080) and info.has_audio and abs(info.duration - 16) < 0.5
    assert isinstance(ffmpeg.scene_changes(source, 0.4), list)


@needs_ffmpeg
def test_render_vertical_1080p_with_captions(source, tmp_path):
    t = make_transcript()
    words = [w for w in t.words() if w.end < 15]
    p = editplan.plan(words, words[0].start, words[-1].end)
    res = render.render(source, p, str(tmp_path / "out"), "clip1")
    assert (res.width, res.height) == (1080, 1920)
    assert abs(res.duration - p.duration) < 0.6
    assert res.cover_path.endswith(".jpg")
