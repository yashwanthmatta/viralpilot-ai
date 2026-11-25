"""Deterministic quality control for a rendered short.

Every check measures the actual output file with FFmpeg/ffprobe, so a clip
only passes when the file itself is right. Each check says whether a
re-render can fix it (``retryable``), which the pipeline uses to decide
between one bounded retry and discarding the clip.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field

from . import ffmpeg

# Short-form limits. YouTube Shorts and Facebook Reels both accept 9:16 up to
# 60 s for the widest eligibility; campaigns commonly ask for 15-60 s.
MIN_DURATION_S = 8.0
MAX_DURATION_S = 60.0
TARGET_W, TARGET_H = 1080, 1920
LUFS_RANGE = (-17.0, -11.0)
MAX_BLACK_SHARE = 0.15
MAX_FROZEN_SHARE = 0.30
MAX_SILENT_SHARE = 0.35
MAX_BYTES = 256 * 1024 * 1024


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    retryable: bool = False


@dataclass
class QCReport:
    passed: bool
    checks: list[Check] = field(default_factory=list)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    @property
    def retryable(self) -> bool:
        """True when every failure is one a re-render could fix."""
        return bool(self.failures) and all(c.retryable for c in self.failures)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "checks": [asdict(c) for c in self.checks]}


_LUFS = re.compile(r"I:\s+(-?[0-9.]+) LUFS")
_BLACK = re.compile(r"black_duration:([0-9.]+)")
_FREEZE = re.compile(r"freeze_duration: ([0-9.]+)")


def integrated_lufs(path: str) -> float | None:
    proc = ffmpeg.run(["-i", path, "-vn", "-af", "ebur128=peak=none", "-f", "null", "-"])
    found = _LUFS.findall(proc.stderr)
    return float(found[-1]) if found else None


def black_seconds(path: str) -> float:
    proc = ffmpeg.run(["-i", path, "-an", "-vf", "blackdetect=d=0.5:pix_th=0.10", "-f", "null", "-"])
    return sum(float(x) for x in _BLACK.findall(proc.stderr))


def frozen_seconds(path: str) -> float:
    proc = ffmpeg.run(["-i", path, "-an", "-vf", "freezedetect=n=0.003:d=2", "-f", "null", "-"])
    return sum(float(x) for x in _FREEZE.findall(proc.stderr))


def check(path: str, *, caption_words: int, cover_path: str = "") -> QCReport:
    checks: list[Check] = []

    def add(name: str, ok: bool, detail: str, retryable: bool = False) -> None:
        checks.append(Check(name, bool(ok), detail, retryable))

    if not path or not os.path.exists(path):
        add("file_exists", False, "rendered file is missing", retryable=True)
        return QCReport(False, checks)
    size = os.path.getsize(path)
    add("file_size", 0 < size <= MAX_BYTES, f"{size / 1e6:.1f} MB", retryable=True)

    info = ffmpeg.probe(path)
    add("video_stream", info.has_video, "present" if info.has_video else "missing", retryable=True)
    add("audio_stream", info.has_audio, "present" if info.has_audio else "missing", retryable=True)
    add("resolution", (info.width, info.height) == (TARGET_W, TARGET_H),
        f"{info.width}x{info.height} (need {TARGET_W}x{TARGET_H})", retryable=True)
    add("frame_rate", 23.0 <= info.fps <= 61.0, f"{info.fps:.2f} fps", retryable=True)
    add("duration", MIN_DURATION_S <= info.duration <= MAX_DURATION_S,
        f"{info.duration:.1f}s (allowed {MIN_DURATION_S:.0f}-{MAX_DURATION_S:.0f}s)")
    if not (info.has_video and info.has_audio and info.duration > 0):
        return QCReport(False, checks)

    lufs = integrated_lufs(path)
    lo, hi = LUFS_RANGE
    add("loudness", lufs is not None and lo <= lufs <= hi,
        f"{lufs:.1f} LUFS (target -14)" if lufs is not None else "could not measure", retryable=True)

    silent = sum(e - s for s, e in ffmpeg.silences(path, noise_db=-45, min_len=0.6))
    add("dead_air", silent / info.duration <= MAX_SILENT_SHARE,
        f"{silent:.1f}s silent ({silent / info.duration:.0%})")

    black = black_seconds(path)
    add("black_frames", black / info.duration <= MAX_BLACK_SHARE, f"{black:.1f}s black ({black / info.duration:.0%})")

    frozen = frozen_seconds(path)
    add("frozen_video", frozen / info.duration <= MAX_FROZEN_SHARE,
        f"{frozen:.1f}s frozen ({frozen / info.duration:.0%})")

    add("captions", caption_words >= 5, f"{caption_words} captioned words")
    if cover_path:
        add("cover_image", os.path.exists(cover_path), "present" if os.path.exists(cover_path) else "missing",
            retryable=True)

    return QCReport(all(c.passed for c in checks), checks)
