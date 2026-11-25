"""Speaker-aware 9:16 framing.

Samples frames inside each edit piece, finds faces with OpenCV's bundled
Haar cascade (fast on CPU, no model download), and picks a horizontal crop
centre per piece: the largest face, smoothed against the previous piece so
the camera doesn't jump around. Falls back to centre framing when no face
is found or OpenCV isn't installed.
"""
from __future__ import annotations

from vp_video.editplan import Piece


def _detector():
    try:
        import cv2
    except ImportError:
        return None, None
    if not hasattr(cv2, "CascadeClassifier"):  # OpenCV 5 moved Haar cascades out of core
        return None, None
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    return cv2, (cascade if not cascade.empty() else None)


def face_centres(path: str, pieces: list[Piece], width: int, samples_per_piece: int = 3) -> list[float | None]:
    """Normalised (0..1) x-centre of the dominant face in each piece."""
    cv2, cascade = _detector()
    if cv2 is None or cascade is None:
        return [None] * len(pieces)
    cap = cv2.VideoCapture(path)
    out: list[float | None] = []
    try:
        for p in pieces:
            xs: list[float] = []
            for k in range(samples_per_piece):
                t = p.src_start + (k + 0.5) * p.length / samples_per_piece
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
                ok, frame = cap.read()
                if not ok:
                    continue
                small = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5) if frame.shape[1] > 960 else frame
                scale = frame.shape[1] / small.shape[1]
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                faces = cascade.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(40, 40))
                if len(faces):
                    x, _y, w, _h = max(faces, key=lambda f: f[2] * f[3])
                    xs.append(((x + w / 2) * scale) / width)
            out.append(sorted(xs)[len(xs) // 2] if xs else None)
    finally:
        cap.release()
    return out


def crop_offsets(centres: list[float | None], src_w: int, src_h: int, smoothing: float = 0.6) -> list[int]:
    """Left edge (pixels) of a full-height 9:16 window for each piece."""
    crop_w = min(src_w, int(round(src_h * 9 / 16 / 2)) * 2)
    max_x = src_w - crop_w
    prev = 0.5
    out = []
    for c in centres:
        target = prev if c is None else c
        cur = prev * smoothing + target * (1 - smoothing) if c is not None and out else target
        prev = cur
        x = int(round(cur * src_w - crop_w / 2))
        out.append(max(0, min(max_x, x)))
    return out
