"""transcribe -> clip -> edit through the real job runner, on synthetic media.
The transcriber is a deterministic stand-in (no model download in tests)."""
import shutil

import pytest
from vp_agents.worker import run_job
from vp_shared import db, jobs
from vp_shared.models import Clip, ClipStage, ContentItem, ItemStage, Job, JobStatus, LicenseType, TranscriptCache
from vp_video import ffmpeg, transcribe

from tests.conftest import start_autopilot
from tests.unit.test_video_engine import make_transcript

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


class FakeTranscriber:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def transcribe(self, audio_path):
        self.calls += 1
        return make_transcript()


@pytest.fixture
def fake_tr():
    t = FakeTranscriber()
    transcribe.set_transcriber(t)
    yield t
    transcribe.set_transcriber(None)


def _run_kind(kind):
    with db.session_scope() as s:
        ids = [j.id for j in s.query(Job).filter_by(kind=kind, status=JobStatus.pending)]
    return [run_job(i) for i in ids]


def test_full_local_pipeline(tmp_path, fake_tr, monkeypatch):
    monkeypatch.setenv("MAX_CLIPS_PER_SOURCE", "2")
    src = tmp_path / "src.mp4"
    ffmpeg.run(["-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=40",
                "-f", "lavfi", "-i", "sine=frequency=200:duration=40", "-shortest",
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)])
    start_autopilot()
    with db.session_scope() as s:
        item = ContentItem(fingerprint="p", title="ep", local_path=str(src), content_sha256="abc",
                           license_type=LicenseType.user_owned, stage=ItemStage.imported)
        s.add(item)
        s.flush()
        jobs.enqueue(s, "transcribe.item", f"transcribe:{item.id}", {"item_id": item.id})
        iid = item.id

    assert _run_kind("transcribe.item") == ["succeeded"]
    assert _run_kind("clip.item") == ["succeeded"]
    with db.session_scope() as s:  # non-campaign clips are queued 30 min behind paid work
        for j in s.query(Job).filter_by(kind="edit.clip"):
            j.run_after = jobs.now_utc()
    results = _run_kind("edit.clip")
    assert results and all(r == "succeeded" for r in results)

    with db.session_scope() as s:
        assert s.get(ContentItem, iid).stage == ItemStage.clipped
        clips = s.query(Clip).all()
        assert 1 <= len(clips) <= 2
        for c in clips:
            assert c.stage == ClipStage.rendered and c.render_path.endswith(".mp4")
            assert c.features and c.edit_plan["duration"] > 0
            info = ffmpeg.probe(c.render_path)
            assert (info.width, info.height) == (1080, 1920)
        assert s.query(Job).filter_by(kind="qc.clip").count() == len(clips)
        assert s.query(TranscriptCache).count() == 1


def test_transcript_cache_prevents_retranscribing(tmp_path, fake_tr):
    src = tmp_path / "s.mp4"
    ffmpeg.run(["-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=3",
                "-f", "lavfi", "-i", "sine=duration=3", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
                "-c:a", "aac", str(src)])
    start_autopilot()
    with db.session_scope() as s:
        for n in ("a", "b"):
            it = ContentItem(fingerprint=n, local_path=str(src), content_sha256="same",
                             license_type=LicenseType.user_owned, stage=ItemStage.imported)
            s.add(it)
            s.flush()
            jobs.enqueue(s, "transcribe.item", f"t:{it.id}", {"item_id": it.id})
    _run_kind("transcribe.item")
    assert fake_tr.calls == 1
