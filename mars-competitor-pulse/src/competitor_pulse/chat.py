"""Chat-facing helpers: parse operator text, format acks — never emit raw JSON."""

from __future__ import annotations

import re
from typing import Any

ASSISTANT_DISPLAY_NAME = "Competitor Pulse"

_MODULE_LABELS = {
    "site": "homepage",
    "pricing": "pricing",
    "changelog": "changelog",
    "careers": "careers",
}


def parse_track_message(text: str) -> list[dict[str, Any]] | None:
    """Simple patterns only: ``track FedEx`` / ``watch Acme``.

    Rejects filler phrases (``add a track for Tesla too``) that used to become
    garbage names like ``A Track For Tesla Too``. Prefer alias/LLM intake for
    natural language; this is a last-resort single-company fallback.
    """
    if not text or not text.strip():
        return None
    stripped = text.strip()
    # Whole-message simple form: optional please + verb + 1–3 name tokens.
    m = re.match(
        r"(?:please\s+)?"
        r"(?:track|watch|monitor|pulse(?:\s+on)?)\s+"
        r"([A-Za-z0-9][A-Za-z0-9&.\-]*(?:\s+[A-Za-z0-9][A-Za-z0-9&.\-]*){0,2})"
        r"(?:\s+competitors?)?"
        r"(?:\s+(?:please|now|today|for\s+me))?"
        r"\s*[!.?]?\s*$",
        stripped,
        re.I,
    )
    if not m:
        return None
    raw = m.group(1).strip()
    if not raw:
        return None
    # Ban filler / verb tokens that indicate a multi-word garbage capture.
    banned = {
        "a", "an", "the", "for", "to", "too", "also", "add", "track", "watch",
        "monitor", "pulse", "on", "lets", "let", "please",
    }
    tokens = raw.lower().split()
    if any(tok in banned for tok in tokens):
        return None
    if re.search(r"\s+and\s+", raw, flags=re.I):
        return None
    name = " ".join(part.capitalize() for part in raw.split())
    slug = re.sub(r"[^a-z0-9]+", "", name.lower())
    base = slug or "competitor"
    return [
        {
            "name": name,
            "urls": {
                "site": f"https://www.{base}.com/",
                "pricing": f"https://www.{base}.com/pricing",
                "changelog": f"https://www.{base}.com/changelog",
                "careers": f"https://www.{base}.com/careers",
            },
        }
    ]


def format_watch_ack(
    watchlist: list[dict[str, Any]],
    *,
    allow_net: bool,
    from_chat: bool = False,
) -> str:
    """Plain-English acknowledgment — never JSON."""
    if not watchlist:
        return "No competitors on the watchlist yet."
    names = [((w.get("name") or "").strip() or "Unknown") for w in watchlist]
    if len(names) == 1:
        lead = f"Got it — setting up a watch on **{names[0]}**."
    else:
        lead = f"Got it — watching **{', '.join(names)}**."
    pages: list[str] = []
    for item in watchlist:
        urls = item.get("urls") or {}
        mods = [_MODULE_LABELS.get(k, k) for k in urls if urls.get(k)]
        if mods:
            pages.append(f"{item.get('name')}: {', '.join(mods)}")
    pages_line = ""
    if pages:
        pages_line = "\nPublic pages: " + "; ".join(pages) + "."
    fetch_mode = (
        "Live public fetch is **on**."
        if allow_net
        else "Using offline fixtures (live fetch off)."
    )
    suffix = ""
    if from_chat:
        suffix = "\nI'll pull snapshots and compare against any saved baseline."
    return f"{lead}{pages_line}\n{fetch_mode}{suffix}"


def looks_like_watchlist_json(text: str) -> bool:
    """Detect raw planner / invoke JSON that must not surface in chat."""
    if not text:
        return False
    t = text.strip()
    return (
        t.startswith('{"watchlist"')
        or t.startswith('{"watchlist":')
        or t.startswith('{"competitors"')
        or t.startswith('{"competitors":')
    )


_STATE_LIST_JSON_RE = re.compile(
    r'\{\s*"(?:watchlist|competitors)"\s*:', re.IGNORECASE
)


def contains_watchlist_json(text: str) -> bool:
    """True when text includes raw watchlist/competitors state JSON (chat guards)."""
    if not text:
        return False
    return bool(_STATE_LIST_JSON_RE.search(text))
