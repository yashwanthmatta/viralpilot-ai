"""Thin, safe wrappers around ffprobe / ffmpeg.

Commands are always built as argument lists (never through a shell), so
file names can't inject anything.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess  # noqa: S404  # nosec B404
from dataclasses import dataclass


class FFmpegError(RuntimeError):
    pass


def _bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise FFmpegError(f"{name} is not installed")
    return path


def run(args: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    proc = subprocess.run(  # noqa: S603  # nosec B603
        [_bin("ffmpeg"), "-hide_banner", "-nostdin", *args],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr[-3000:])
    return proc


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    has_video: bool


def probe(path: str) -> MediaInfo:
    proc = subprocess.run(  # noqa: S603  # nosec B603
        [_bin("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed: {proc.stderr[-1000:]}")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fps = 0.0
    if v and v.get("avg_frame_rate", "0/0") != "0/0":
        n, d = v["avg_frame_rate"].split("/")
        fps = float(n) / float(d) if float(d) else 0.0
    return MediaInfo(
        duration=float(data.get("format", {}).get("duration") or 0.0),
        width=int(v.get("width", 0)) if v else 0,
        height=int(v.get("height", 0)) if v else 0,
        fps=fps,
        has_audio=a is not None,
        has_video=v is not None,
    )


_SCENE_RE = re.compile(r"pts_time:([0-9.]+)")


def scene_changes(path: str, threshold: float = 0.35, start: float = 0.0, end: float | None = None) -> list[float]:
    """Cut points (seconds) using FFmpeg's scene score. Lighter than a
    separate scene-detection library and good enough to avoid cutting a clip
    mid-shot."""
    args = ["-ss", f"{start:.3f}"]
    if end is not None:
        args += ["-to", f"{end:.3f}"]
    args += ["-i", path, "-an", "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"]
    proc = run(args)
    return [start + float(t) for t in _SCENE_RE.findall(proc.stderr)]


_SIL_START = re.compile(r"silence_start: ([0-9.]+)")
_SIL_END = re.compile(r"silence_end: ([0-9.]+)")


def silences(path: str, noise_db: int = -35, min_len: float = 0.5) -> list[tuple[float, float]]:
    proc = run(["-i", path, "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_len}", "-f", "null", "-"])
    starts = [float(x) for x in _SIL_START.findall(proc.stderr)]
    ends = [float(x) for x in _SIL_END.findall(proc.stderr)]
    return list(zip(starts, ends, strict=False))


def extract_audio(path: str, out_wav: str) -> str:
    run(["-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out_wav])
    return out_wav
