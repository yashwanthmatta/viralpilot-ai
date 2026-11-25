import io

import httpx
from vp_agents.stages import acquisition
from vp_agents.worker import run_job
from vp_shared import db, jobs, netsafety
from vp_shared.models import ContentItem, ItemStage, Job, LicenseType, Source, SourceKind

from tests.conftest import start_autopilot

FEED = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:cc="http://creativecommons.org/ns#">
<channel><title>Test</title>
 <item><guid>ep1</guid><title>Owned episode</title>
   <enclosure url="https://media.example/ep1.mp4" type="video/mp4" length="5"/></item>
 <item><guid>ep2</guid><title>NC episode</title>
   <cc:license>https://creativecommons.org/licenses/by-nc/4.0/</cc:license>
   <enclosure url="https://media.example/ep2.mp4" type="video/mp4" length="5"/></item>
 <item><guid>ep3</guid><title>Not media</title>
   <enclosure url="https://media.example/ep3.pdf" type="application/pdf" length="5"/></item>
</channel></rss>"""


def _source(s, lic=LicenseType.user_owned):
    src = Source(name="My podcast", kind=SourceKind.rss, url="https://feed.example/rss",
                 license_type=lic, rights_evidence="I am the creator of this feed")
    s.add(src)
    s.flush()
    return src


def test_parse_and_rights_gate(s):
    src = _source(s)
    counts = acquisition.ingest_entries(s, src, acquisition.parse_feed(FEED))
    assert counts == {"new": 1, "duplicate": 0, "rejected": 2}
    stages = {i.external_id: i.stage for i in s.query(ContentItem)}
    assert stages == {"ep1": ItemStage.discovered, "ep2": ItemStage.rights_rejected,
                      "ep3": ItemStage.rights_rejected}
    # second poll: nothing reprocessed
    counts = acquisition.ingest_entries(s, src, acquisition.parse_feed(FEED))
    assert counts == {"new": 0, "duplicate": 3, "rejected": 0}
    assert s.query(Job).filter_by(kind="import.item").count() == 1


def test_billion_laughs_is_refused():
    import pytest
    from defusedxml import EntitiesForbidden

    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><rss>&b;</rss>'
    with pytest.raises(EntitiesForbidden):
        acquisition.parse_feed(bomb)


class _Resp:
    def __init__(self, body, status=200):
        self.status_code, self._body, self.headers = status, body, {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)

    def iter_bytes(self, n):
        buf = io.BytesIO(self._body)
        while chunk := buf.read(n):
            yield chunk


def test_import_downloads_dedupes_and_queues_transcription(monkeypatch):
    monkeypatch.setattr(netsafety, "safe_stream", lambda *a, **k: _Resp(b"same-bytes"))
    start_autopilot()
    with db.session_scope() as s:
        src = _source(s)
        a = ContentItem(source_id=src.id, fingerprint="a", media_url="https://m/a", license_type=LicenseType.user_owned)
        b = ContentItem(source_id=src.id, fingerprint="b", media_url="https://m/b", license_type=LicenseType.user_owned)
        s.add_all([a, b])
        s.flush()
        ja = jobs.enqueue(s, "import.item", "ia", {"item_id": a.id}).id
        jb = jobs.enqueue(s, "import.item", "ib", {"item_id": b.id}).id
        ida, idb = a.id, b.id
    assert run_job(ja) == "succeeded"
    assert run_job(jb) == "succeeded"
    with db.session_scope() as s:
        assert s.get(ContentItem, ida).stage == ItemStage.imported
        assert s.get(ContentItem, idb).stage == ItemStage.discarded  # identical file
        assert s.query(Job).filter_by(kind="transcribe.item").count() == 1


def test_import_size_cap(monkeypatch):
    monkeypatch.setenv("MAX_IMPORT_BYTES", "4")
    monkeypatch.setattr(netsafety, "safe_stream", lambda *a, **k: _Resp(b"too many bytes"))
    start_autopilot()
    with db.session_scope() as s:
        it = ContentItem(fingerprint="c", media_url="https://m/c", license_type=LicenseType.user_owned)
        s.add(it)
        s.flush()
        jid = jobs.enqueue(s, "import.item", "ic", {"item_id": it.id}).id
        iid = it.id
    assert run_job(jid) == "succeeded"
    with db.session_scope() as s:
        assert s.get(ContentItem, iid).stage == ItemStage.discarded
