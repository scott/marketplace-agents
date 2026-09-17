"""Warm conversational replies for chat / help — no pulse fetch."""

from __future__ import annotations

from competitor_pulse.persona import help_message, welcome_message

_TEMPLATE_OTHER = (
    "Didn't quite catch that — want a pulse or a quick how-to?\n\n"
    "Name companies to watch (e.g. `track FedEx`) or ask **what do you do?**"
)


def _llm_reply(intent: str, human_text: str) -> str | None:
    try:
        from competitor_pulse.llm import get_llm, harness_env_available

        if not harness_env_available():
            return None

        intent_guide = {
            "chat": "Greet warmly, invite them to name companies to track.",
            "help": "Explain capabilities, how to track/notify/baselines, and v1 limits.",
            "other": "Ask a short clarifying question in character.",
        }.get(intent, "Reply helpfully.")

        llm = get_llm(temperature=0.4)
        prompt = (
            "You are Competitor Pulse — a sharp, dry product/GTM researcher embedded in "
            "MARS chat. Helpful, not corporate. Contractions OK. No 'Certainly!' or "
            "helpdesk filler. Stay honest about v1: public web only, stub notify, no "
            "competitor logins.\n\n"
            f"Intent: {intent}. {intent_guide}\n"
            "Keep it under 120 words. Markdown OK. Do not invent competitor deltas or "
            "fetch results.\n\n"
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
        return _TEMPLATE_OTHER
    return welcome_message()


def conversational_reply(intent: str, human_text: str) -> str:
    """Harness LLM when available; solid templates offline for tests."""
    llm_text = _llm_reply(intent, human_text)
    if llm_text:
        return llm_text
    return template_reply(intent)
