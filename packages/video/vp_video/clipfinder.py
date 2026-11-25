"""Find and rank short-form clip candidates from a word-timed transcript.

Fully deterministic and explainable: every score is a weighted sum of named
features computed from the transcript, and every clip records which features
drove its score. No model call is made here. The weights come from the
strategy (``DEFAULT_WEIGHTS`` until the growth engine has real performance
data to adjust them).

These are *heuristic proxies*, not predictions of views. The dashboard
labels them as such.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from vp_video.transcribe import Transcript, Word

HOOK_WORDS = {
    "why", "how", "secret", "mistake", "never", "nobody", "stop", "truth", "wrong", "actually",
    "biggest", "worst", "best", "only", "imagine", "here's", "this", "warning", "crazy", "insane",
}
EMOTION_WORDS = {
    "amazing", "incredible", "love", "hate", "afraid", "scared", "terrified", "shocked", "angry", "crying",
    "cried", "excited", "unbelievable", "insane", "crazy", "furious", "heartbroken", "proud", "wow",
}
STORY_MARKERS = {"when i", "then", "so i", "i remember", "story", "happened", "one day", "years ago", "turns out", "suddenly"}
INSIGHT_MARKERS = {"the key", "the reason", "here's", "tip", "lesson", "learned", "because", "the trick", "the problem",
                   "what most people", "the difference", "rule", "step"}
HUMOR_MARKERS = {"laugh", "funny", "joke", "hilarious", "haha", "lol", "ridiculous"}
FILLERS = {"um", "uh", "erm", "hmm", "like", "basically", "literally"}

DEFAULT_WEIGHTS = {
    "hook": 0.24,
    "emotion": 0.14,
    "story": 0.12,
    "insight": 0.16,
    "humor": 0.08,
    "pacing": 0.10,
    "density": 0.08,
    "duration_fit": 0.08,
    "filler_penalty": -0.10,
    "silence_penalty": -0.10,
}

_SENT_END = re.compile(r"[.!?…]['\"”)]?$")


@dataclass
class Sentence:
    start: float
    end: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Candidate:
    start: float
    end: float
    text: str
    score: float
    features: dict[str, float]
    reason: str
    words: list[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


def sentences(t: Transcript) -> list[Sentence]:
    out: list[Sentence] = []
    cur: list[Word] = []
    for w in t.words():
        cur.append(w)
        if _SENT_END.search(w.text) or (len(cur) > 40):
            out.append(Sentence(cur[0].start, cur[-1].end, cur))
            cur = []
    if cur:
        out.append(Sentence(cur[0].start, cur[-1].end, cur))
    return out


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9' ]+", "", s.lower())


def _hits(text: str, vocab: set[str]) -> int:
    t = f" {_norm(text)} "
    return sum(t.count(f" {v} ") for v in vocab)


def features(words: list[Word], first: Sentence, min_s: float, max_s: float, target_s: float) -> dict[str, float]:
    text = " ".join(w.text for w in words)
    n = max(len(words), 1)
    dur = max(words[-1].end - words[0].start, 0.1)
    first_text = first.text
    hook = 0.0
    hook += 0.35 if first_text.strip().endswith("?") else 0.0
    hook += min(_hits(first_text, HOOK_WORDS) * 0.2, 0.4)
    hook += 0.15 if re.search(r"\b\d+\b", first_text) else 0.0
    hook += 0.1 if re.search(r"\byou\b", first_text.lower()) else 0.0
    hook += 0.15 if (first.end - first.start) <= 4.0 else 0.0
    wps = n / dur
    pacing = max(0.0, 1.0 - abs(wps - 2.8) / 1.6)  # ~2.2-3.4 words/sec reads well on mobile
    gaps = sum(max(0.0, b.start - a.end) for a, b in zip(words, words[1:], strict=False))
    silence_ratio = gaps / dur
    density = min(len({_norm(w.text) for w in words if len(w.text) > 3}) / n * 1.5, 1.0)
    fit = max(0.0, 1.0 - abs(dur - target_s) / (max_s - min_s))
    per_min = 60.0 / dur
    return {
        "hook": min(hook, 1.0),
        "emotion": min(_hits(text, EMOTION_WORDS) * per_min / 6.0 + text.count("!") * 0.05, 1.0),
        "story": min(_hits(text, STORY_MARKERS) * per_min / 4.0, 1.0),
        "insight": min(_hits(text, INSIGHT_MARKERS) * per_min / 4.0, 1.0),
        "humor": min(_hits(text, HUMOR_MARKERS) * per_min / 3.0, 1.0),
        "pacing": pacing,
        "density": density,
        "duration_fit": fit,
        "filler_penalty": min(_hits(text, FILLERS) / n * 8.0, 1.0),
        "silence_penalty": min(max(silence_ratio - 0.15, 0.0) * 3.0, 1.0),
    }


def _reason(f: dict[str, float], w: dict[str, float]) -> str:
    contrib = sorted(((k, f[k] * w.get(k, 0)) for k in f), key=lambda kv: -kv[1])
    top = [f"{k} {f[k]:.2f}" for k, c in contrib if c > 0.02][:3]
    neg = [f"{k} {f[k]:.2f}" for k, c in contrib if c < -0.02]
    s = "strongest signals: " + (", ".join(top) or "none")
    return s + (f"; penalties: {', '.join(neg)}" if neg else "")


def find_clips(
    t: Transcript,
    *,
    min_s: float = 15.0,
    max_s: float = 59.0,
    target_s: float = 35.0,
    max_clips: int = 3,
    min_score: float = 0.25,
    weights: dict[str, float] | None = None,
) -> list[Candidate]:
    """Windows always start and end on sentence boundaries; overlapping
    candidates are suppressed so the output clips are distinct."""
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    sents = sentences(t)
    cands: list[Candidate] = []
    for i, first in enumerate(sents):
        words: list[Word] = []
        for j in range(i, len(sents)):
            words = words + sents[j].words
            dur = words[-1].end - words[0].start
            if dur > max_s:
                break
            if dur < min_s:
                continue
            f = features(words, first, min_s, max_s, target_s)
            score = sum(f[k] * w.get(k, 0.0) for k in f)
            cands.append(Candidate(words[0].start, words[-1].end, " ".join(x.text for x in words),
                                   round(score, 4), f, _reason(f, w), list(words)))
    cands.sort(key=lambda c: -c.score)
    chosen: list[Candidate] = []
    for c in cands:
        if c.score < min_score:
            break
        if any(_overlap(c, o) > 0.3 for o in chosen):
            continue
        chosen.append(c)
        if len(chosen) >= max_clips:
            break
    return chosen


def _overlap(a: Candidate, b: Candidate) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    return inter / min(a.duration, b.duration)
