"""Edit planning: silence removal, timeline remapping, keyword choice.

The plan is pure data (JSON-serialisable) so it can be stored on the clip,
inspected on the dashboard and re-rendered without re-analysis.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from vp_video.clipfinder import EMOTION_WORDS, FILLERS, HOOK_WORDS, INSIGHT_MARKERS
from vp_video.transcribe import Word

MAX_GAP = 0.45      # pauses longer than this are shortened ...
KEEP_GAP = 0.12     # ... to this much breathing room
LEAD_IN = 0.08
TAIL = 0.35


@dataclass
class Piece:
    src_start: float
    src_end: float
    out_start: float
    zoom: float = 1.0

    @property
    def length(self) -> float:
        return self.src_end - self.src_start


@dataclass
class TimedWord:
    start: float  # on the OUTPUT timeline
    end: float
    text: str
    keyword: bool


@dataclass
class EditPlan:
    pieces: list[Piece]
    words: list[TimedWord]
    duration: float
    removed_s: float

    def to_dict(self) -> dict:
        return {"pieces": [asdict(p) for p in self.pieces], "words": [asdict(w) for w in self.words],
                "duration": self.duration, "removed_s": self.removed_s}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", s.lower())


def pick_keywords(words: list[Word]) -> set[int]:
    """Indexes of words to highlight: numbers, emphasis vocabulary, and the
    most repeated meaningful words (the topic)."""
    emph = HOOK_WORDS | EMOTION_WORDS | {m.split()[-1] for m in INSIGHT_MARKERS}
    counts: dict[str, int] = {}
    for w in words:
        n = _norm(w.text)
        if len(n) > 4 and n not in FILLERS:
            counts[n] = counts.get(n, 0) + 1
    topic = {k for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:3] if v >= 2}
    out = set()
    for i, w in enumerate(words):
        n = _norm(w.text)
        if re.fullmatch(r"\d[\d,.%$]*", n) or n in emph or n in topic:
            out.add(i)
    return out


def plan(words: list[Word], clip_start: float, clip_end: float, *, punch_every: int = 3) -> EditPlan:
    """Cut long pauses and filler-only gaps, then remap word times onto the
    new, tighter timeline. Every ``punch_every``-th piece gets a gentle zoom
    as a pattern interrupt."""
    ws = [w for w in words if w.start >= clip_start - 0.01 and w.end <= clip_end + 0.01]
    if not ws:
        return EditPlan([Piece(clip_start, clip_end, 0.0)], [], clip_end - clip_start, 0.0)
    spans: list[list[float]] = [[max(clip_start, ws[0].start - LEAD_IN), ws[0].end]]
    for prev, w in zip(ws, ws[1:], strict=False):
        if w.start - prev.end > MAX_GAP:
            spans[-1][1] = prev.end + KEEP_GAP / 2
            spans.append([w.start - KEEP_GAP / 2, w.end])
        else:
            spans[-1][1] = w.end
    spans[-1][1] = min(clip_end + TAIL, spans[-1][1] + TAIL)

    pieces: list[Piece] = []
    t = 0.0
    for i, (a, b) in enumerate(spans):
        zoom = 1.12 if punch_every and i % punch_every == punch_every - 1 else 1.0
        pieces.append(Piece(a, b, t, zoom))
        t += b - a

    def remap(x: float) -> float:
        for p in pieces:
            if p.src_start - 1e-6 <= x <= p.src_end + 1e-6:
                return p.out_start + (x - p.src_start)
        # inside a removed gap: snap to the start of the next piece
        nxt = next((p for p in pieces if p.src_start > x), pieces[-1])
        return nxt.out_start

    keys = pick_keywords(ws)
    timed = [TimedWord(round(remap(w.start), 3), round(remap(w.end), 3), w.text, i in keys) for i, w in enumerate(ws)]
    total = clip_end - clip_start
    return EditPlan(pieces, timed, round(t, 3), round(max(total - t, 0.0), 3))
