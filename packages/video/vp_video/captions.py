"""Animated word-by-word captions as an ASS subtitle file (rendered by libass).

Words appear in short chunks; the word being spoken pops (bigger, accent
colour) and keywords stay highlighted. Styling is a brand preset so every
video looks consistent.
"""
from __future__ import annotations

from dataclasses import dataclass

from vp_video.editplan import TimedWord


@dataclass(frozen=True)
class BrandStyle:
    font: str = "DejaVu Sans"
    size: int = 92
    primary: str = "&H00FFFFFF"   # ASS colours are &HAABBGGRR
    active: str = "&H0000E5FF"    # yellow-orange for the word being spoken
    keyword: str = "&H00FFB07C"   # soft blue for keywords
    outline: str = "&H00000000"
    outline_w: int = 6
    shadow: int = 2
    margin_v: int = 560           # sits above platform UI at the bottom
    max_words: int = 3
    max_chunk_s: float = 1.6


def _ts(t: float) -> str:
    t = max(t, 0.0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _esc(s: str) -> str:
    return s.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def chunk(words: list[TimedWord], style: BrandStyle) -> list[list[TimedWord]]:
    out: list[list[TimedWord]] = []
    cur: list[TimedWord] = []
    for w in words:
        if cur and (len(cur) >= style.max_words or w.end - cur[0].start > style.max_chunk_s
                    or cur[-1].text.endswith((".", "?", "!", ","))):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def build_ass(words: list[TimedWord], style: BrandStyle | None = None, width: int = 1080, height: int = 1920) -> str:
    st = style or BrandStyle()
    head = (
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {width}\nPlayResY: {height}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        f"Style: Cap,{st.font},{st.size},{st.primary},{st.primary},{st.outline},&H64000000,1,0,0,0,100,100,0,0,1,"
        f"{st.outline_w},{st.shadow},2,80,80,{st.margin_v},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for ch in chunk(words, st):
        for i, w in enumerate(ch):
            start = w.start
            end = ch[i + 1].start if i + 1 < len(ch) else max(w.end, w.start + 0.25)
            parts = []
            for j, x in enumerate(ch):
                txt = _esc(x.text.upper())
                if j == i:
                    parts.append(r"{\c" + st.active + r"\fscx112\fscy112}" + txt + r"{\r}")
                elif x.keyword:
                    parts.append(r"{\c" + st.keyword + "}" + txt + r"{\r}")
                else:
                    parts.append(txt)
            pop = r"{\t(0,80,\fscx104\fscy104)\t(80,160,\fscx100\fscy100)}" if i == 0 else ""
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{pop}{' '.join(parts)}")
    return head + "\n".join(lines) + "\n"
