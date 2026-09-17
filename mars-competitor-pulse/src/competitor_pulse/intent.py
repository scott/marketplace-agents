"""Early intent routing for MARS chat — before gather / pulse workflow."""

from __future__ import annotations

import re
from typing import Any

from competitor_pulse.intake_parse import (
    is_generic_message,
    parse_watchlist_from_message,
)

_CHAT_RE = re.compile(
    r"^(?:"
    r"hi|hello|hey|yo|sup|howdy|hiya|"
    r"good\s+(?:morning|afternoon|evening)|"
    r"what'?s\s+up|whats\s+up|"
    r"what'?s\s+good|whats\s+good|"
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


def _has_overlay_pulse(
    *,
    overlay_watchlist: list[dict[str, Any]] | None,
    overlay_preset: str | None,
    human_text: str,
) -> bool:
    if overlay_watchlist:
        return True
    preset = (overlay_preset or "").strip().lower()
    if preset == "spacexai":
        return True
    if "SPACEXAI_PRESET" in (human_text or ""):
        return True
    return False


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

    Order:
    1. Empty human + no overlay pulse signals → pulse (programmatic)
    2. Overlay watchlist / spacexai preset → pulse
    3. Parsed competitors/watchlist → pulse
    4. Clear help regex → help (before bare ``watch`` tracking — e.g. modules help)
    5. Non-generic tracking request → pulse
    6. Clear chat regex / is_generic_message → chat
    7. Else if API key: direct-HTTP LLM classify (stream:false)
    8. Else → other

    Never short-circuit to pulse solely because ``state_watchlist`` is already
    set — greetings/help after a track must still route chat/help.
    ``state_watchlist`` is accepted for API compatibility but ignored for routing.
    """
    _ = state_watchlist  # intentionally unused for routing (see docstring)

    stripped = (human_text or "").strip()
    overlay_pulse = _has_overlay_pulse(
        overlay_watchlist=overlay_watchlist,
        overlay_preset=overlay_preset,
        human_text=human_text or "",
    )

    # 1. Empty human + no overlays → pulse (programmatic / fixture path)
    if not stripped and not overlay_pulse:
        return "pulse"

    # 2. Overlay / preset pulse
    if overlay_pulse:
        return "pulse"

    parsed = parsed_nl if parsed_nl is not None else parse_watchlist_from_message(stripped)

    # 3. Resolved competitors from NL → pulse
    if parsed.get("competitors") or parsed.get("watchlist"):
        return "pulse"

    # 4. Clear help (before tracking keyword "watch" in help questions)
    if stripped and is_help_message(stripped):
        return "help"

    # 5. Tracking request without being generic chat
    if parsed.get("is_tracking_request") and not parsed.get("is_generic"):
        return "pulse"

    # 6. Clear chat / generic openers
    if stripped and is_chat_message(stripped):
        return "chat"

    # 7. LLM classify (direct HTTP) when key present
    if stripped:
        try:
            from competitor_pulse.intent_llm import classify_intent_llm

            llm_intent = classify_intent_llm(stripped)
            if llm_intent in {"chat", "help", "pulse", "other"}:
                return llm_intent
        except Exception:
            pass

    # 8. Offline / failure fallback
    return "other"
