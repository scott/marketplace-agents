"""Early intent routing for MARS chat — before gather / pulse workflow."""

from __future__ import annotations

import re
from typing import Any

from competitor_pulse.intake_parse import (
    is_generic_message,
    is_tracking_request,
    parse_watchlist_from_message,
)

_CHAT_RE = re.compile(
    r"^(?:"
    r"hi|hello|hey|yo|sup|howdy|hiya|"
    r"good\s+(?:morning|afternoon|evening)|"
    r"what'?s\s+up|whats\s+up|"
    r"run|go|start|ok|okay|yes|yep|sure|"
    r"please|thanks|thank\s+you|thx|cheers|nice|cool|"
    r"lol|haha|ha|"
    r"bye|goodbye|see\s+ya|later"
    r")\s*[!.?]*$",
    re.IGNORECASE,
)

_HELP_RE = re.compile(
    r"\b("
    r"what\s+do\s+you\s+do|"
    r"who\s+are\s+you|"
    r"what\s+are\s+you|"
    r"how\s+does\s+(?:this|it)\s+work|"
    r"how\s+do\s+(?:i|we)\s+(?:use|track|notify|start|run)|"
    r"what\s+can\s+you\s+do|"
    r"help(?:\s+me)?|"
    r"explain|"
    r"capabilities|"
    r"limitations?|limits?|"
    r"how\s+(?:to|do\s+i)\s+track|"
    r"how\s+(?:to|do\s+i)\s+notify|"
    r"what\s+is\s+(?:a\s+)?baseline|"
    r"baselines?|"
    r"notify(?:\s+gate)?|"
    r"mars\s+tips?|"
    r"getting\s+started|"
    r"instructions?|"
    r"modules?|"
    r"what\s+do\s+you\s+watch|"
    r"what'?s\s+material|"
    r"material\s+bar|"
    r"approve|"
    r"deny"
    r")\b",
    re.IGNORECASE,
)


def is_chat_message(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if is_generic_message(stripped):
        return True
    return bool(_CHAT_RE.match(stripped))


def is_help_message(text: str) -> bool:
    return bool(_HELP_RE.search((text or "").strip()))


def classify_intent(
    human_text: str,
    *,
    state_watchlist: list[dict[str, Any]] | None = None,
    overlay_watchlist: list[dict[str, Any]] | None = None,
    overlay_preset: str | None = None,
    parsed_nl: dict[str, Any] | None = None,
) -> str:
    """Classify latest human message into chat | help | pulse | other.

    ``pulse`` keeps the existing watchlist → gather → analyze workflow.
    Programmatic invokes with no human text still route to ``pulse``.
    """
    if state_watchlist:
        return "pulse"

    if overlay_watchlist:
        return "pulse"

    preset = (overlay_preset or "").strip().lower()
    if preset == "spacexai" or "SPACEXAI_PRESET" in (human_text or ""):
        return "pulse"

    stripped = (human_text or "").strip()

    # Fixture / smoke path when invoked without chat text.
    if not stripped:
        return "pulse"

    parsed = parsed_nl if parsed_nl is not None else parse_watchlist_from_message(stripped)

    if is_help_message(stripped):
        return "help"

    if parsed.get("competitors") or parsed.get("watchlist"):
        return "pulse"

    if parsed.get("is_tracking_request") and not parsed.get("is_generic"):
        return "pulse"

    if is_chat_message(stripped):
        return "chat"

    return "other"
