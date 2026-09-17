"""Warm conversational replies for chat / help — no pulse fetch.

MARS/doctl concatenates harness ``llm.invoke`` token streams into prompt
``text``. If we also emit the same prose as an ``AIMessage``, greetings
duplicate. Keep Sol persona templates only (no LLM) so chat/help stay
prose-once and never stream JSON.
"""

from __future__ import annotations

from competitor_pulse.persona import (
    help_message,
    other_message,
    welcome_message,
)


def template_reply(intent: str) -> str:
    if intent == "help":
        return help_message()
    if intent == "other":
        return other_message()
    return welcome_message()


def conversational_reply(intent: str, human_text: str) -> str:
    """Deterministic Sol persona templates — never llm.invoke on the chat path."""
    _ = human_text  # reserved for future template variants
    return template_reply(intent)
