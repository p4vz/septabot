"""Lightweight entity extraction from free-form Telegram messages.

Kept deterministic (regex, no LLM) so we can decide what data to fetch
*before* spending a Hermes call. If the regex misses something subtle,
Hermes still gets the snapshot we did fetch and can ask the user to
rephrase — better than a slow function-calling round-trip per message.
"""
from __future__ import annotations

import re
from typing import Optional

from app.data.rail_lines import LINE_ALIASES, RAIL_LINE_NAMES


# ── Route extraction ───────────────────────────────────────────────────────

_FROM_TO_RE = re.compile(
    r"\bfrom\s+(?P<orig>.+?)\s+to\s+(?P<dest>.+?)(?:[.?!,;]|$)",
    re.IGNORECASE,
)

# "drive to Center City", "train to airport" — destination only.
_TO_VERB_RE = re.compile(
    r"\b(?:get|go|going|drive|driving|train|bus|ride|riding|head|heading|"
    r"commute|commuting|travel|traveling|take(?:\s+the\s+train)?)\s+to\s+"
    r"(?P<dest>.+?)(?:[.?!,;]|$)",
    re.IGNORECASE,
)

# Time-of-day qualifiers that often trail a destination phrase. We strip
# them so "from Wayne to Center City tonight" parses as ("Wayne", "Center City").
_TIME_TAIL_RE = re.compile(
    r"\s+(?:tonight|today|tomorrow|now|right\s+now|"
    r"this\s+(?:morning|afternoon|evening)|"
    r"in\s+the\s+(?:morning|afternoon|evening)|"
    r"at\s+\d[\d:apm.\s]*|"
    r"in\s+\d+\s*(?:min(?:ute)?s?|h(?:ou)?rs?))\s*$",
    re.IGNORECASE,
)

_FILLER = re.compile(r"\s+", re.UNICODE)


def _clean_place(s: str) -> str:
    s = s.strip().strip(",.?!;:")
    s = _TIME_TAIL_RE.sub("", s).strip()
    s = _FILLER.sub(" ", s)
    return s


def extract_route(text: str, default_origin: Optional[str] = None) -> Optional[tuple[str, str]]:
    """Return (origin, destination) if the message contains route intent.

    Tries "from X to Y" first. Falls back to "<verb> to Y" with
    `default_origin` filling in the start point.
    """
    m = _FROM_TO_RE.search(text)
    if m:
        orig = _clean_place(m.group("orig"))
        dest = _clean_place(m.group("dest"))
        if orig and dest:
            return orig, dest

    if default_origin:
        m = _TO_VERB_RE.search(text)
        if m:
            dest = _clean_place(m.group("dest"))
            if dest and dest.lower() not in ("work", "home", "school", "the office"):
                return default_origin, dest

    return None


# ── Rail-line detection ────────────────────────────────────────────────────

# Build a single ordered list of (phrase, canonical_line) tuples sorted by
# phrase length descending, so the most specific match wins. Aliases from
# `data/rail_lines.py` come first because they're curated to be safe
# multi-word phrases ("paoli line", not bare "paoli").
_LINE_PHRASES: list[tuple[str, str]] = []
for _canonical, _aliases in LINE_ALIASES.items():
    for _alias in _aliases:
        _LINE_PHRASES.append((_alias.lower(), _canonical))
for _canonical in RAIL_LINE_NAMES:
    _LINE_PHRASES.append((_canonical.lower(), _canonical))
_LINE_PHRASES.sort(key=lambda x: -len(x[0]))


def extract_line(text: str) -> Optional[str]:
    """Return a canonical Regional Rail line name if mentioned, else None."""
    t = f" {text.lower()} "
    for phrase, canonical in _LINE_PHRASES:
        # Pad with spaces so "paoli line" doesn't match inside another word.
        if f" {phrase} " in t or f" {phrase}." in t or f" {phrase}?" in t:
            return canonical
    return None
