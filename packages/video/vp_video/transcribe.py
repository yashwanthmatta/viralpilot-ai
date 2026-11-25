"""Speech-to-text with word timestamps (faster-whisper, runs on the worker CPU).

Local inference costs nothing per minute, so the expensive part is CPU time.
Results are cached by the file's SHA-256 in the `transcripts` table, so the
same file is never transcribed twice.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Word:
    start: float
    end: float
    text: str
    prob: float = 1.0


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    language: str
    duration: float
    segments: list[Segment]

    def words(self) -> list[Word]:
        return [w for s in self.segments for w in s.words]

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "duration": self.duration,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text,
                 "words": [{"start": w.start, "end": w.end, "text": w.text, "prob": w.prob} for w in s.words]}
                for s in self.segments
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        return cls(
            language=d.get("language", ""),
            duration=float(d.get("duration", 0.0)),
            segments=[
                Segment(s["start"], s["end"], s["text"], [Word(w["start"], w["end"], w["text"], w.get("prob", 1.0))
                                                          for w in s.get("words", [])])
                for s in d.get("segments", [])
            ],
        )


class Transcriber(Protocol):
    name: str

    def transcribe(self, audio_path: str) -> Transcript: ...


class TranscriberUnavailable(RuntimeError):
    pass


class WhisperTranscriber:
    def __init__(self, model: str | None = None, compute_type: str = "int8"):
        self.model_name = model or os.environ.get("WHISPER_MODEL", "base.en")
        self.compute_type = compute_type
        self.name = f"faster-whisper:{self.model_name}"
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:  # pragma: no cover - depends on install
                raise TranscriberUnavailable("faster-whisper is not installed on this worker") from e
            self._model = WhisperModel(self.model_name, device="cpu", compute_type=self.compute_type)
        return self._model

    def transcribe(self, audio_path: str) -> Transcript:
        model = self._load()
        segs, info = model.transcribe(audio_path, word_timestamps=True, vad_filter=True, beam_size=1)
        out: list[Segment] = []
        for s in segs:
            words = [Word(float(w.start), float(w.end), w.word.strip(), float(w.probability)) for w in (s.words or [])]
            out.append(Segment(float(s.start), float(s.end), s.text.strip(), words))
        return Transcript(language=info.language, duration=float(info.duration), segments=out)


_default: Transcriber | None = None


def get_transcriber() -> Transcriber:
    global _default
    if _default is None:
        _default = WhisperTranscriber()
    return _default


def set_transcriber(t: Transcriber | None) -> None:
    """Tests inject a deterministic transcriber here."""
    global _default
    _default = t
