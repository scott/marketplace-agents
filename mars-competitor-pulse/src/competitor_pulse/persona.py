"""Pulse persona — system prompt and user-facing copy builders.

Canonical voice/copy is pending in ``PULSE-PERSONA-COPY.md`` (Sol).
This module scaffolds the API surface; final strings land in a follow-up PR.
"""

from __future__ import annotations

from typing import Any

# TODO(Sol): replace from PULSE-PERSONA-COPY.md
PULSE_SYSTEM_PROMPT = (
    "You are Competitor Pulse, a competitor intelligence assistant for MARS chat."
)


def welcome_message() -> str:
    """Greeting for chat intent.

    TODO(Sol): replace body from PULSE-PERSONA-COPY.md.
    """
    return (
        "Hey — I'm **Competitor Pulse**, your slightly obsessive GTM researcher.\n\n"
        "Name a company (or a few) and I'll watch their public pages — site, pricing, "
        "changelog, careers — and diff them against a baseline.\n\n"
        "Try `track FedEx`, `Pulse on Cursor and Perplexity`, or ask **how this works**."
    )


def help_message() -> str:
    """Help / how-to reply for help intent.

    TODO(Sol): replace body from PULSE-PERSONA-COPY.md.
    """
    return (
        "I'm **Competitor Pulse** — sharp, dry, and allergic to noisy alerts.\n\n"
        "**What I do:** you name competitors → I fetch public pages → diff against a saved "
        "baseline → send you a plain-English brief when something actually moves.\n\n"
        "**How to use it:**\n"
        "- `track OpenAI and Anthropic` — add companies to your watchlist\n"
        "- `track Cursor and alert on Slack` — opt into the notify gate (approval required)\n"
        "- Re-run later to see real diffs; first run is a **first look** baseline, not a crisis\n\n"
        "**v1 limits (honest):** public web only, no competitor logins, notify is a stub until "
        "you approve on material changes. Offline fixtures work when live fetch is off."
    )


def quiet_message(names: list[str], modules: list[str]) -> str:
    """Quiet-run summary when no material changes were detected.

    TODO(Sol): replace body from PULSE-PERSONA-COPY.md.
    """
    raise NotImplementedError("quiet_message: pending PULSE-PERSONA-COPY.md (Sol)")


def ask_body(
    *,
    channel: str,
    delta_count: int,
    names: list[str],
    highlights: str,
    notify_draft: str,
) -> str:
    """Human-in-the-loop notify approval interrupt body.

    TODO(Sol): replace body from PULSE-PERSONA-COPY.md.
    """
    raise NotImplementedError("ask_body: pending PULSE-PERSONA-COPY.md (Sol)")


def brief_prose(
    *,
    first_run: bool,
    deltas: list[dict[str, Any]],
    counterpositions: list[str] | None = None,
) -> str:
    """Markdown brief for material or first-look pulse runs.

    TODO(Sol): replace body from PULSE-PERSONA-COPY.md.
    """
    raise NotImplementedError("brief_prose: pending PULSE-PERSONA-COPY.md (Sol)")
