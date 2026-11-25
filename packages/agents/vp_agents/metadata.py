"""Hooks, titles, descriptions and hashtags for a clip.

Two writers share one output shape:

* ``rules``: deterministic, free, always available. Used when no Anthropic
  key is set, when the budget can't cover a model call, or when the model
  call fails.
* ``claude``: one Claude call with structured JSON output. The model is set
  by ``METADATA_MODEL`` (cost routing: one cheap, short call per clip; the
  cost is reserved against the budget before the call and the real cost from
  ``usage`` is recorded after).

Whatever writer runs, ``enforce`` then applies the rules that are not
optional: attribution for CC BY content, a paid-promotion disclosure for
campaign clips, platform length limits, and no engagement bait.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass, field

DEFAULT_MODEL = "claude-opus-5-5"
# USD per million tokens (input, output). Unknown models are priced at the
# highest rate here so the reservation never under-counts.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-2": (8.0, 40.0),
}
MAX_OUTPUT_TOKENS = 1200
TITLE_MAX = 100
HASHTAGS_MAX = 12

_STOP = set("""a an the and or but if then so to of in on at by for with from up out is are was were be been being it
its this that these those i you he she we they me my your our their him her them what which who whom how why when
where just really very can could would should will shall do does did not no yes have has had like get got go going
gonna um uh yeah okay ok oh well right know think thing things about there here into over than because also""".split())
_BAIT = re.compile(r"\b(like and subscribe|smash (the )?like|comment below to win|follow for part 2|sub4sub|f4f)\b", re.I)


@dataclass
class MetaInput:
    transcript: str
    source_title: str = ""
    attribution: str = ""
    license_type: str = ""
    campaign_name: str = ""
    campaign_creator: str = ""
    campaign_requirements: str = ""
    platforms: list[str] = field(default_factory=list)
    niche: str = ""
    handle: str = ""


@dataclass
class Metadata:
    hook: str
    title: str
    description: str
    hashtags: list[str]
    writer: str = "rules"
    model: str = ""
    cost_usd: float = 0.0
    paid_promotion: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------- rules writer

def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if len(s.strip()) > 3]


def keywords(text: str, n: int = 6) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z']{2,}", text)]
    counts = Counter(w for w in words if w not in _STOP)
    return [w for w, _ in counts.most_common(n)]


def rules(m: MetaInput) -> Metadata:
    sents = _sentences(m.transcript) or [m.transcript.strip() or m.source_title or "Watch this"]
    # Prefer a question or an exclamation as the hook: they read as openers.
    hook = next((s for s in sents[:6] if s.endswith(("?", "!"))), sents[0])
    hook = _trim(hook, 90)
    title = _trim(hook.rstrip(".") if len(hook) >= 20 else f"{hook.rstrip('.')} | {m.source_title}", TITLE_MAX)
    kws = keywords(m.transcript)
    tags = [f"#{k}" for k in kws[:5]]
    if m.niche:
        tags.insert(0, "#" + re.sub(r"[^a-z0-9]", "", m.niche.lower()))
    desc = _trim(" ".join(sents[:2]), 300)
    return Metadata(hook=hook, title=title, description=desc, hashtags=tags, writer="rules")


def _trim(s: str, limit: int) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= limit:
        return s
    cut = s[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(",;:-") + "…"


# ----------------------------------------------------------------- claude writer

SYSTEM = (
    "You write metadata for short vertical videos (YouTube Shorts, Facebook Reels). "
    "Write a scroll-stopping but accurate hook and title from what is actually said in the transcript. "
    "Never invent facts, quotes, numbers or outcomes that the transcript does not contain. "
    "No clickbait that misrepresents the clip, no engagement bait (for example 'like and subscribe to win'), "
    "no medical, financial or legal claims beyond what the speaker said. "
    "Follow the campaign requirements when they are given. Plain text only, no markdown."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "hook": {"type": "string", "description": "On-screen opening line, at most 90 characters"},
        "title": {"type": "string", "description": "Video title, at most 90 characters"},
        "description": {"type": "string", "description": "One or two sentences, at most 300 characters"},
        "hashtags": {"type": "array", "items": {"type": "string"}, "description": "3 to 8 relevant hashtags"},
    },
    "required": ["hook", "title", "description", "hashtags"],
    "additionalProperties": False,
}


def model_name() -> str:
    return os.environ.get("METADATA_MODEL", DEFAULT_MODEL)


def claude_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _prompt(m: MetaInput) -> str:
    parts = [f"Transcript of the clip:\n<transcript>\n{m.transcript[:6000]}\n</transcript>"]
    if m.source_title:
        parts.append(f"Original video title: {m.source_title}")
    if m.niche:
        parts.append(f"Channel niche: {m.niche}")
    if m.campaign_requirements:
        parts.append(f"Campaign requirements from the brand (follow them):\n{m.campaign_requirements[:2000]}")
    if m.platforms:
        parts.append(f"Platforms: {', '.join(m.platforms)}")
    return "\n\n".join(parts)


def estimate_usd(m: MetaInput, model: str | None = None) -> float:
    model = model or model_name()
    pin, pout = PRICES.get(model, max(PRICES.values()))
    in_tokens = (len(SYSTEM) + len(_prompt(m)) + len(json.dumps(SCHEMA))) / 3.0 + 50
    return round((in_tokens * pin + MAX_OUTPUT_TOKENS * pout) / 1_000_000, 6)


def cost_of(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES.get(model, max(PRICES.values()))
    return round((input_tokens * pin + output_tokens * pout) / 1_000_000, 6)


_client = None


def set_client(client) -> None:
    """Tests install a fake client here."""
    global _client
    _client = client


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(max_retries=2, timeout=60.0)
    return _client


def claude(m: MetaInput) -> Metadata:
    model = model_name()
    kwargs = dict(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM,
        messages=[{"role": "user", "content": _prompt(m)}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    client = _get_client()
    if model.startswith(("claude-opus-5", "claude-fable-5", "claude-sonnet-5-5")):
        # If a safety classifier declines, let the API retry on another model
        # inside the same call instead of failing the clip.
        resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
    else:
        resp = client.messages.create(**kwargs)
    cost = cost_of(model, resp.usage.input_tokens, resp.usage.output_tokens)
    if resp.stop_reason == "refusal":
        raise MetadataError("model declined", cost)
    if resp.stop_reason == "max_tokens":
        raise MetadataError("model output was cut off", cost)
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise MetadataError(f"invalid JSON from model: {e}", cost) from e
    return Metadata(hook=str(data["hook"]), title=str(data["title"]), description=str(data["description"]),
                    hashtags=[str(h) for h in data.get("hashtags", [])], writer="claude",
                    model=getattr(resp, "model", model), cost_usd=cost)


class MetadataError(Exception):
    def __init__(self, msg: str, cost_usd: float = 0.0):
        super().__init__(msg)
        self.cost_usd = cost_usd


# ----------------------------------------------------------------- non-optional rules

def _tag(t: str) -> str:
    t = re.sub(r"[^\w]", "", t.lstrip("#"))
    return f"#{t}" if t else ""


def enforce(meta: Metadata, m: MetaInput) -> Metadata:
    notes: list[str] = []
    for f in ("hook", "title", "description"):
        val = getattr(meta, f)
        cleaned = _BAIT.sub("", val)
        if cleaned != val:
            notes.append(f"removed engagement bait from {f}")
        setattr(meta, f, re.sub(r"\s+", " ", cleaned).strip())
    meta.hook = _trim(meta.hook, 90)
    meta.title = _trim(meta.title or meta.hook, TITLE_MAX)

    tags: list[str] = []
    for t in meta.hashtags:
        t = _tag(t)
        if t and t.lower() not in {x.lower() for x in tags}:
            tags.append(t)
    if "youtube" in m.platforms and "#shorts" not in {t.lower() for t in tags}:
        tags.insert(0, "#Shorts")
    lines = [meta.description]

    if m.campaign_name:
        meta.paid_promotion = True
        brand = m.campaign_creator or m.campaign_name
        lines.append(f"Paid partnership with {brand}.")
        if "#ad" not in {t.lower() for t in tags}:
            tags.insert(0, "#ad")
        notes.append("paid promotion disclosed")
    if m.license_type.startswith("cc_by"):
        if not m.attribution:
            raise ValueError("CC BY content needs an attribution line")
        lines.append(f"Credit: {m.attribution}")
        notes.append("attribution added")
    if m.handle:
        lines.append(f"Follow {m.handle} for more.")
    meta.hashtags = tags[:HASHTAGS_MAX]
    meta.description = "\n\n".join(x for x in lines if x) + ("\n\n" + " ".join(meta.hashtags) if meta.hashtags else "")
    meta.description = meta.description[:4900]  # YouTube's description limit is 5000
    meta.notes = meta.notes + notes
    return meta
