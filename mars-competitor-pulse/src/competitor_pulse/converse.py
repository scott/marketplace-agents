"""Warm conversational replies for chat / help — no pulse fetch."""

from __future__ import annotations

from competitor_pulse.persona import (
    PULSE_SYSTEM_PROMPT,
    help_message,
    other_message,
    welcome_message,
)


def _llm_reply(intent: str, human_text: str) -> str | None:
    try:
        from competitor_pulse.llm import get_llm, harness_env_available

        if not harness_env_available():
            return None

        intent_guide = {
            "chat": (
                "Greet as Competitor Pulse. Keep who you are, what you watch, "
                "won't notify without OK, and how to start (three starters). "
                "Do not start a track run."
            ),
            "help": (
                "Explain how track/pulse works, baseline vs material, notify ask, "
                "and honest v1 limits (public web only, stub notify)."
            ),
            "other": "Ask a short clarifying question in character.",
        }.get(intent, "Reply helpfully.")

        llm = get_llm(temperature=0.4)
        prompt = (
            f"{PULSE_SYSTEM_PROMPT}\n\n"
            f"Intent: {intent}. {intent_guide}\n"
            "Keep it under 160 words. Markdown OK. Do not invent competitor deltas or "
            "fetch results. Never emit JSON or stage dumps.\n\n"
            f"User: {human_text}\n\n"
            "Reply:"
        )
        response = llm.invoke(prompt)
        content = getattr(response, "content", "") or ""
        if isinstance(content, list):
            content = " ".join(str(part) for part in content)
        text = str(content).strip()
        return text or None
    except Exception:
        return None


def template_reply(intent: str) -> str:
    if intent == "help":
        return help_message()
    if intent == "other":
        return other_message()
    return welcome_message()


def conversational_reply(intent: str, human_text: str) -> str:
    """Harness LLM when available; solid templates offline for tests."""
    llm_text = _llm_reply(intent, human_text)
    if llm_text:
        return llm_text
    return template_reply(intent)
