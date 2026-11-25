"""Render a vertical 1080x1920 short from an edit plan with FFmpeg.

Per piece: trim, speaker-aware 9:16 crop, optional punch-in zoom. Then
concatenate (silences already removed by the plan), burn in animated
captions, and finish the audio (high-pass, gentle compression, loudness
normalised to -14 LUFS, the common target for short-form platforms).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from vp_video import ffmpeg
from vp_video.captions import BrandStyle, build_ass
from vp_video.editplan import EditPlan
from vp_video.framing import crop_offsets, face_centres

OUT_W, OUT_H, FPS = 1080, 1920, 30


@dataclass
class RenderResult:
    video_path: str
    cover_path: str
    duration: float
    width: int
    height: int


def _esc_filter_path(p: str) -> str:
    return p.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def build_filter(plan: EditPlan, info: ffmpeg.MediaInfo, offsets: list[int], seek: float, ass_path: str | None) -> str:
    narrow = info.width / max(info.height, 1) <= 9 / 16 + 1e-3
    crop_w = min(info.width, int(round(info.height * 9 / 16 / 2)) * 2)
    parts: list[str] = []
    labels: list[str] = []
    for i, p in enumerate(plan.pieces):
        a, b = p.src_start - seek, p.src_end - seek
        v = f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS"
        if narrow:
            v += f",scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H}"
        else:
            v += f",crop={crop_w}:{info.height}:{offsets[i]}:0"
        if p.zoom > 1.0:
            v += f",scale=iw*{p.zoom}:ih*{p.zoom},crop=iw/{p.zoom}:ih/{p.zoom}"
        v += f",scale={OUT_W}:{OUT_H},setsar=1,fps={FPS}[v{i}]"
        parts.append(v)
        parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    parts.append(f"{''.join(labels)}concat=n={len(plan.pieces)}:v=1:a=1[vc][ac]")
    vchain = "[vc]"
    if ass_path:
        parts.append(f"[vc]ass=filename='{_esc_filter_path(ass_path)}'[vs]")
        vchain = "[vs]"
    parts.append(f"{vchain}format=yuv420p[vout]")
    parts.append("[ac]highpass=f=80,acompressor=threshold=-20dB:ratio=3:attack=5:release=120,"
                 "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")
    return ";".join(parts)


def render(src: str, plan: EditPlan, out_dir: str, name: str, *, style: BrandStyle | None = None,
           captions: bool = True) -> RenderResult:
    info = ffmpeg.probe(src)
    if not info.has_video or not info.has_audio:
        raise ffmpeg.FFmpegError("source needs both video and audio")
    os.makedirs(out_dir, exist_ok=True)
    seek = max(0.0, plan.pieces[0].src_start - 1.0)
    until = plan.pieces[-1].src_end + 1.0
    centres = face_centres(src, plan.pieces, info.width)
    offsets = crop_offsets(centres, info.width, info.height)
    ass_path = None
    if captions and plan.words:
        ass_path = os.path.join(out_dir, f"{name}.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(build_ass(plan.words, style, OUT_W, OUT_H))
    out = os.path.join(out_dir, f"{name}.mp4")
    ffmpeg.run([
        "-y", "-ss", f"{seek:.3f}", "-to", f"{until:.3f}", "-i", src,
        "-filter_complex", build_filter(plan, info, offsets, seek, ass_path),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", os.environ.get("RENDER_PRESET", "veryfast"), "-crf", "20",
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out,
    ])
    cover = os.path.join(out_dir, f"{name}.jpg")
    ffmpeg.run(["-y", "-ss", f"{min(1.0, plan.duration / 2):.2f}", "-i", out, "-frames:v", "1", "-q:v", "3", cover])
    res = ffmpeg.probe(out)
    return RenderResult(out, cover, res.duration, res.width, res.height)
