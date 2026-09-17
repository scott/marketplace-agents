"""Warm conversational replies for chat / help / other — no pulse fetch.

MARS/doctl concatenates harness ``llm.invoke`` token streams into prompt
``text``. Never call ``get_llm()`` / ``llm.invoke`` here. Optional LLM replies
use direct HTTP ``stream: false`` (see ``intent_llm``). Offline / no key /
HTTP failure → Sol persona templates so chat stays prose-once and leak-safe.
"""

from __future__ import annotations

from competitor_pulse.hygiene import hygiene_text
from competitor_pulse.intent import is_chat_message, is_help_message
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


def _prefer_template(intent: str, human_text: str) -> bool:
    """Known-topic help and bare greetings stay on cheap templates."""
    text = (human_text or "").strip()
    if intent == "help" and text and is_help_message(text):
        # Topic help / how-to copy is curated; use templates.
        return True
    if intent == "chat" and text and is_chat_message(text):
        # Short openers: stable welcome (golden voice); LLM not required.
        return True
    return False


def conversational_reply(intent: str, human_text: str) -> str:
    """Sol templates by default; direct-HTTP LLM for freeform chat/other/help.

    Never uses LangChain ``llm.invoke`` (doctl text leak). Hygiene on output.
    """
    text = human_text or ""
    if not _prefer_template(intent, text):
        try:
            from competitor_pulse.intent_llm import conversational_reply_llm

            llm_text = conversational_reply_llm(intent, text)
            if llm_text and llm_text.strip():
                return hygiene_text(llm_text.strip())
        except Exception:
            pass
    return hygiene_text(template_reply(intent, text))
