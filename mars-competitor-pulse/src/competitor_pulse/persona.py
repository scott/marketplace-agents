"""Pulse persona — system prompt and user-facing copy builders.

Canonical voice/copy: Shop design/PULSE-PERSONA-COPY.md (Sol).
"""

from __future__ import annotations

from datetime import date
from typing import Any

PULSE_SYSTEM_PROMPT = """You are Competitor Pulse, a product and GTM research colleague.

Job: watch a named competitor list on the public web (site, pricing, changelog, careers), diff against the last baseline, and write a short counterposition brief a PM can paste into Slack. First run establishes a baseline; it is not a crisis.

Hard rules:
- Public web only. Never log into competitor sites, create accounts, or scrape behind login.
- Never invent deltas. If a URL failed or content is missing, say so plainly.
- Never notify (Slack, email, or any outbound) without explicit user approval on this run.
- v1 notify is stubbed: Approve records intent in run state; it does not send a real message. Be honest about that when asked.
- Prefer short, concrete sentences. No helpdesk filler ("Certainly", "I'd be happy to", "Of course").
- Never use em-dashes (—) or double hyphens (--). Use commas, periods, semicolons, colons, or parentheses.
- Do not dump stage names, JSON, or label soup ("intake:", "status: ok", "review site_copy_change") into user-facing chat.
- When the user is just chatting or asking for help, answer in prose. Do not start a track run unless they clearly ask to track or pulse competitors.
"""

_MODULE_PLAIN = {
    "site": "homepage / product site",
    "pricing": "pricing page",
    "changelog": "changelog / release notes",
    "careers": "careers page",
}


def module_plain(module: str) -> str:
    key = (module or "").strip().lower()
    return _MODULE_PLAIN.get(key, module or "page")


def welcome_message() -> str:
    """Greeting for chat intent (hi / empty opener)."""
    return (
        "I'm Competitor Pulse — a research colleague for product and GTM.\n\n"
        "I watch the public web for companies you name: site, pricing, changelog, and careers. "
        "I diff against your last baseline and write a short brief you can paste to Slack.\n\n"
        "I will not notify anyone without your OK. On the first pass I only set a baseline so "
        "later runs have something honest to compare.\n\n"
        "Try one of these:\n"
        "• Track OpenAI, Anthropic, and Google\n"
        "• Pulse on Cursor and Perplexity\n"
        "• Track Cursor and alert on Slack\n\n"
        "Or ask what I can do."
    )


def help_message() -> str:
    """Help / how-to reply for help intent."""
    return (
        "Here's how I work:\n\n"
        "1. You name competitors in plain English (Track … / Pulse on …).\n"
        "2. I fetch public pages for site, pricing, changelog, and careers.\n"
        "3. I diff against your baseline. First run only sets the baseline.\n"
        "4. If something material moved, I write a brief. If you asked for an alert, I ask before any notify.\n"
        "5. Approve keeps the brief and records a stub notify in this run. Deny keeps the brief quiet. "
        "Neither contacts competitors.\n\n"
        "I do not: log into competitor sites, scrape behind login, invent changes, auto-notify, "
        "or send real Slack/email in v1.\n\n"
        "Modules I watch: site · pricing · changelog · careers.\n"
        "Material means a real public-page delta vs baseline, not every crawl blip.\n\n"
        "Say Track CompanyA, CompanyB to start, or name a channel (Slack / email) when you want the notify ask."
    )


def other_message() -> str:
    """Ambiguous / other intent fallback."""
    return (
        "Didn't quite catch that. Want a pulse or a quick how-to?\n\n"
        "Name companies to watch (e.g. Track FedEx) or ask what I can do."
    )


def quiet_message(names: list[str], modules: list[str] | None = None) -> str:
    """Quiet-run chat line when no material changes were detected."""
    _ = modules  # machine detail stays on state; not dumped in chat
    line = "Nothing material moved since your last baseline — staying quiet."
    if names:
        names_s = ", ".join(names)
        line += (
            f"\n\nWatchlist still set ({names_s}); "
            "say Track … again anytime you want a fresh pass."
        )
    return line


def ask_body(
    *,
    channel: str,
    delta_count: int,
    names: list[str],
    highlights: str,
    notify_draft: str,
) -> str:
    """Human-in-the-loop notify approval interrupt body."""
    names_s = ", ".join(names) if names else "your watchlist"
    return (
        f"Want me to send this pulse notify via {channel}?\n\n"
        f"{delta_count} material change(s) across {names_s}.\n\n"
        f"Highlights:\n{highlights}\n\n"
        "Brief: ready in this run (kept local unless you approve notify).\n\n"
        f"Notify draft:\n{notify_draft}\n\n"
        "I will not: contact competitors, create accounts, or scrape behind login.\n"
        "v1 note: Approve stubs notify in run state; it does not send a real Slack/email yet."
    )


def ask_highlights(deltas: list[dict[str, Any]], limit: int = 7) -> str:
    """Prose bullets for ask body — no module/review-type labels."""
    lines: list[str] = []
    for d in deltas[:limit]:
        name = d.get("competitor") or "?"
        summary = (d.get("summary") or "").strip() or "public page moved"
        lines.append(f"- {name}: {summary}")
    return "\n".join(lines) if lines else "- (none)"


def first_look_message(
    names: list[str],
    *,
    gaps: list[str] | None = None,
) -> str:
    """Chat-facing first-look / baseline established copy."""
    names_s = ", ".join(names) if names else "your watchlist"
    if gaps:
        gap_s = ", ".join(gaps)
        return (
            f"Baseline set for {names_s}, with gaps: {gap_s}. "
            "Those pages were unreachable; I did not invent content for them.\n\n"
            "No notify on a first look."
        )
    return (
        f"Baseline set for {names_s}.\n\n"
        "I saved public snapshots for site, pricing, changelog, and careers. "
        "Next run will only flag material moves against this baseline.\n\n"
        "No notify on a first look."
    )


def material_chat_message(names: list[str], *, notify_off: bool = True) -> str:
    """Chat-facing material report when notify ask is skipped."""
    names_s = ", ".join(names) if names else "your watchlist"
    if notify_off:
        return (
            f"Material moves on {names_s}. "
            "Brief is ready in this run; notify is off so I did not ask."
        )
    return f"Material moves on {names_s}. Brief is ready in this run."


def deny_message() -> str:
    return "Got it — staying quiet. Brief stays in this run; nothing sent."


def approve_stub_message(notify_id: str) -> str:
    nid = notify_id or "stub"
    return (
        f"Recorded stub notify ({nid}). Brief kept; no real Slack/email send in v1."
    )


def notify_draft_text(
    *,
    delta_count: int,
    names: list[str],
    deltas: list[dict[str, Any]],
) -> str:
    """Short pasteable notify draft."""
    names_s = ", ".join(names) if names else "watchlist"
    lines = [f"Pulse: {delta_count} material change(s) on {names_s}."]
    for d in deltas[:7]:
        name = d.get("competitor") or "?"
        summary = (d.get("summary") or "").strip() or "public page moved"
        lines.append(f"- {name}: {summary}")
    return "\n".join(lines)


def response_implication(delta: dict[str, Any]) -> str:
    """One-sentence counterposition implication (no Counter/review labels)."""
    comp = delta.get("competitor") or "Competitor"
    module = delta.get("module") or "page"
    summary = (delta.get("summary") or "").lower()
    if delta.get("is_baseline_capture"):
        return ""
    if module == "pricing":
        return (
            f"If {comp}'s pricing move undercuts us, pressure-test our mid-market packet this week."
        )
    if module == "changelog":
        return (
            f"If {comp} shipped a customer-visible capability, decide whether GTM needs a response."
        )
    if module == "careers":
        return (
            f"Hiring on {comp}'s careers page may signal focus areas; skim roles against our roadmap."
        )
    if "error" in summary or "downtime" in summary:
        return (
            f"{comp}'s site may be unstable; hold competitive outbound until their page is back."
        )
    return (
        f"Skim {comp}'s homepage shift for positioning changes before the next customer call."
    )


def brief_prose(
    *,
    first_run: bool,
    deltas: list[dict[str, Any]],
    counterpositions: list[str] | None = None,
    run_label: str | None = None,
    gaps: list[str] | None = None,
) -> str:
    """Markdown brief for material or first-look pulse runs."""
    names = sorted({str(d.get("competitor") or "?") for d in deltas}) or []
    names_s = ", ".join(names) if names else "your watchlist"

    if first_run:
        if gaps:
            gap_s = ", ".join(gaps)
            return (
                f"Baseline set for {names_s}, with gaps: {gap_s}. "
                "Those pages were unreachable; I did not invent content for them.\n\n"
                "No notify on a first look."
            )
        lines = [
            f"Baseline set for {names_s}.",
            "",
            "I saved public snapshots for site, pricing, changelog, and careers. "
            "Next run will only flag material moves against this baseline.",
            "",
            "No notify on a first look.",
        ]
        if deltas:
            lines.extend(["", "## What we captured", ""])
            for d in deltas:
                comp = d.get("competitor") or "?"
                mod = module_plain(str(d.get("module") or ""))
                summary = d.get("summary") or ""
                url = d.get("evidence_url") or d.get("url") or ""
                bullet = f"- **{comp}** ({mod}): {summary}"
                if url:
                    bullet += f". Evidence: {url}"
                lines.append(bullet)
        return "\n".join(lines)

    label = run_label or date.today().isoformat()
    thesis = (
        f"{len(deltas)} material public-page change(s) across {names_s}."
        if deltas
        else f"Material moves on {names_s}."
    )
    lines = [
        f"# Competitor pulse — {label}",
        "",
        thesis,
        "",
        "## What changed",
    ]
    for d in deltas:
        comp = d.get("competitor") or "?"
        mod = module_plain(str(d.get("module") or ""))
        summary = d.get("summary") or ""
        url = d.get("evidence_url") or d.get("url") or ""
        bullet = f"- **{comp}** ({mod}): {summary}"
        if url:
            bullet += f". Evidence: {url}"
        lines.append(bullet)

    responses = [c for c in (counterpositions or []) if c]
    if not responses:
        responses = [response_implication(d) for d in deltas[:7]]
        responses = [r for r in responses if r]
    if responses:
        lines.extend(["", "## How we might respond"])
        for r in responses:
            lines.append(f"- {r}")
    return "\n".join(lines)
