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
    r"run|go|start|"
    r"please|thanks|thank\s+you|thx|cheers|nice|cool|"
    r"lol|haha|ha|"
    r"bye|goodbye|see\s+ya|later"
    r")\s*[!.?]*$",
    re.IGNORECASE,
)

# Bare yes/ok only when no pending track plan (confirm handled separately).
_STANDALONE_CHAT_ACK_RE = re.compile(
    r"^(?:yes|yep|yeah|yup|sure|ok|okay)\s*[!.?]*$",
    re.IGNORECASE,
)

_TRACK_CONFIRM_RE = re.compile(
    r"^(?:"
    r"yes|yep|yeah|yup|sure|ok|okay|"
    r"go ahead|go for it|do it|proceed|"
    r"track it|track them|start|run it|"
    r"sounds good|let'?s go|lets go|"
    r"confirmed|confirm"
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
    if _STANDALONE_CHAT_ACK_RE.match(stripped):
        return True
    return bool(_CHAT_RE.match(stripped))


def is_track_confirm(text: str) -> bool:
    """True when the operator confirms a pending track plan."""
    stripped = (text or "").strip()
    if not stripped:
        return False
    return bool(_TRACK_CONFIRM_RE.match(stripped))


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
    pending_track: dict[str, Any] | None = None,
) -> str:
    """Classify latest human message into chat | help | track_plan | pulse | other.

    ``track_plan`` = NL extracted companies; reply with plan + confirm (no gather).
    ``pulse`` = confirmed track or programmatic invoke → gather → analyze workflow.

    Order:
    1. Empty human + no overlay pulse signals → pulse (programmatic)
    2. Overlay watchlist / spacexai preset → pulse
    3. Pending track + confirm phrase → pulse
    4. Parsed competitors from NL → track_plan (Ghost Writer plan-before-act)
    5. Clear help regex → help
    6. Non-generic tracking request (unresolved) → track_plan (intake may block)
    7. Clear chat regex / is_generic_message → chat
    8. Else if API key: direct-HTTP LLM classify (stream:false)
    9. Else → other

    Never short-circuit to pulse solely because ``state_watchlist`` is already
    set — greetings/help after a track must still route chat/help.
    """
    _ = state_watchlist  # API compat; routing uses pending_track + parsed NL

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

    # 3. Confirm pending track plan → pulse
    if pending_track and stripped and is_track_confirm(stripped):
        return "pulse"

    # 4. Resolved competitors from NL → track_plan (discuss → plan → ask)
    if parsed.get("competitors") or parsed.get("watchlist"):
        return "track_plan"

    # 5. Clear help (before tracking keyword "watch" in help questions)
    if stripped and is_help_message(stripped):
        return "help"

    # 6. Tracking request without being generic chat
    if parsed.get("is_tracking_request") and not parsed.get("is_generic"):
        return "track_plan"

    # 7. Clear chat / generic openers
    if stripped and is_chat_message(stripped):
        return "chat"

    # 8. LLM classify (direct HTTP) when key present
    if stripped:
        try:
            from competitor_pulse.intent_llm import classify_intent_llm

            llm_intent = classify_intent_llm(stripped)
            if llm_intent == "pulse":
                # Ambiguous LLM pulse without resolved names stays conversational.
                return "other"
            if llm_intent in {"chat", "help", "other"}:
                return llm_intent
        except Exception:
            pass

    # 9. Offline / failure fallback
    return "other"
