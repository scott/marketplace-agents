"""Direct HTTP inference for intent classify + chat replies (MARS-safe).

Scar: MARS/doctl concatenates LangChain/harness ``llm.invoke`` token streams
into prompt ``text``. Never use ``get_llm()`` / ``ChatOpenAI`` / ``llm.invoke``
on the classify or conversational-reply path. Call OpenAI-compatible
``POST {base}/chat/completions`` with ``stream: false`` and parse JSON
``choices[0].message.content`` yourself.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from competitor_pulse.llm import harness_env_available, resolve_llm_env
from competitor_pulse.persona import (
    ASK_SYSTEM_PROMPT,
    BRIEF_SYSTEM_PROMPT,
    CHAT_SYSTEM_PROMPT,
    PULSE_SYSTEM_PROMPT,
    TRACK_PLAN_SYSTEM_PROMPT,
)

_VALID_INTENTS = frozenset({"chat", "help", "pulse", "other"})

_CLASSIFY_SYSTEM = """You classify user messages for Competitor Pulse, a product/GTM research colleague that watches public competitor pages.

Return exactly one word, lowercase, nothing else:
- chat — greetings, small talk, banter, jokes, weather, how-are-you, unclear chit-chat, brainstorming companies without a clear track ask yet
- help — how the agent works, capabilities, baselines, modules, notify, approve/deny
- pulse — user clearly confirmed they want to track/watch/pulse/monitor named competitors NOW (after a plan or explicit "track X now")
- other — anything else that is not clearly chat, help, or pulse

Greetings and small talk → chat. How-it-works → help. Name competitors to track without confirm → other (plan gate handles track). Clear yes/go ahead after a plan → pulse."""

_MODE_PROMPTS = {
    "chat": CHAT_SYSTEM_PROMPT,
    "help": CHAT_SYSTEM_PROMPT,
    "other": CHAT_SYSTEM_PROMPT,
    "track_plan": TRACK_PLAN_SYSTEM_PROMPT,
    "brief": BRIEF_SYSTEM_PROMPT,
    "ask": ASK_SYSTEM_PROMPT,
    "pulse": PULSE_SYSTEM_PROMPT,
}


def _inference_ready() -> bool:
    """True when an API key is configured (harness or OpenAI)."""
    return harness_env_available()


def chat_completions(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
    max_tokens: int = 400,
    timeout_s: float = 20.0,
) -> str | None:
    """POST /chat/completions with stream:false. Returns content or None."""
    if not _inference_ready():
        return None
    resolved = resolve_llm_env()
    api_key = resolved.get("api_key")
    if not api_key:
        return None
    base = (resolved.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    model = resolved.get("model") or "gpt-4o-mini"
    url = f"{base}/chat/completions"
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        choices = payload.get("choices") or []
        if not choices:
            return None
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            content = " ".join(
                part.get("text", str(part)) if isinstance(part, dict) else str(part)
                for part in content
            )
        text = str(content or "").strip()
        return text or None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError, KeyError):
        return None
    except Exception:
        return None


def classify_intent_llm(human_text: str) -> str | None:
    """LLM intent → chat|help|pulse|other, or None on failure / no key."""
    stripped = (human_text or "").strip()
    if not stripped:
        return None
    content = chat_completions(
        [
            {"role": "system", "content": _CLASSIFY_SYSTEM},
            {"role": "user", "content": stripped},
        ],
        temperature=0.0,
        max_tokens=8,
    )
    if not content:
        return None
    token = re.split(r"\s+", content.strip().lower(), maxsplit=1)[0]
    token = token.strip(".,!?:;\"'")
    if token in _VALID_INTENTS:
        return token
    return None


def conversational_reply_llm(intent: str, human_text: str) -> str | None:
    """LLM chat/help/other reply under Pulse persona. None → caller uses templates."""
    stripped = (human_text or "").strip()
    if not stripped:
        return None
    label = intent if intent in _VALID_INTENTS else "chat"
    system = _MODE_PROMPTS.get(label, CHAT_SYSTEM_PROMPT)
    user = (
        f"Intent hint: {label}\n"
        f"User message:\n{stripped}\n\n"
        "Reply in plain prose for the operator. If suggesting a company, end with an offer to track it."
    )
    return chat_completions(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
        max_tokens=450,
    )


# Re-export for tests / callers that want a single import surface.
def inference_configured() -> bool:
    return _inference_ready()
