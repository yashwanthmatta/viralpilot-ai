"""Free-tier batch mode: one run drains every due job inline, no Redis."""
import shutil

import pytest
from vp_shared import db, jobs
from vp_shared.models import Clip, ClipStage, ContentItem, ItemStage, Job, JobStatus, LicenseType
from vp_video import ffmpeg, transcribe
from vp_worker import batch

from tests.conftest import start_autopilot
from tests.unit.test_video_pipeline import FakeTranscriber

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def test_batch_runs_the_pipeline_across_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setenv("MAX_CLIPS_PER_SOURCE", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    transcribe.set_transcriber(FakeTranscriber())
    src = tmp_path / "media" / "src.mp4"
    src.parent.mkdir(parents=True)
    ffmpeg.run(["-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=40",
                "-f", "lavfi", "-i", "sine=frequency=200:duration=40", "-shortest",
                "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)])
    try:
        start_autopilot()
        with db.session_scope() as s:
            item = ContentItem(fingerprint="b", title="ep", local_path=str(src), content_sha256="bb",
                               license_type=LicenseType.user_owned, stage=ItemStage.imported)
            s.add(item)
            s.flush()
            jobs.enqueue(s, "transcribe.item", f"transcribe:{item.id}", {"item_id": item.id})

        first = batch.run(120)
        assert first["outcomes"].get("succeeded", 0) >= 2  # transcribe + clip
        with db.session_scope() as s:
            assert s.query(Clip).count() == 1
            edit = s.query(Job).filter_by(kind="edit.clip").one()
            assert edit.status == JobStatus.pending  # non-campaign edits wait for a later run
            edit.run_after = jobs.now_utc()

        batch.run(120)  # next scheduled run: edit -> qc -> metadata
        with db.session_scope() as s:
            clip = s.query(Clip).one()
            assert clip.stage == ClipStage.ready and clip.title
            assert s.query(Job).filter_by(kind="metadata.clip").one().status == JobStatus.blocked  # no account yet
    finally:
        transcribe.set_transcriber(None)


def test_prune_keeps_clips_waiting_to_post(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path))
    keep, drop = tmp_path / "keep.mp4", tmp_path / "drop.mp4"
    keep.write_bytes(b"1" * 10)
    drop.write_bytes(b"2" * 10)
    with db.session_scope() as s:
        item = ContentItem(fingerprint="p", stage=ItemStage.clipped)
        s.add(item)
        s.flush()
        s.add_all([Clip(item_id=item.id, start_s=0, end_s=1, stage=ClipStage.qc_passed, render_path=str(keep)),
                   Clip(item_id=item.id, start_s=0, end_s=1, stage=ClipStage.qc_failed, render_path=str(drop))])
    assert batch.prune_media() == 10
    assert keep.exists() and not drop.exists()
