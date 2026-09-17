"""Warm conversational replies for chat / help — no pulse fetch.

MARS/doctl concatenates harness ``llm.invoke`` token streams into prompt
``text``. If we also emit the same prose as an ``AIMessage``, greetings
duplicate. Keep Sol persona templates only (no LLM) so chat/help stay
prose-once and never stream JSON.
"""

from __future__ import annotations

from competitor_pulse.hygiene import hygiene_text
from competitor_pulse.persona import (
    help_for_topic,
    other_message,
    welcome_message,
)


def template_reply(intent: str, human_text: str = "") -> str:
    if intent == "help":
        return help_for_topic(human_text)
    if intent == "other":
        return other_message()
    return welcome_message()


def conversational_reply(intent: str, human_text: str) -> str:
    """Deterministic Sol persona templates — never llm.invoke on the chat path."""
    return hygiene_text(template_reply(intent, human_text))
