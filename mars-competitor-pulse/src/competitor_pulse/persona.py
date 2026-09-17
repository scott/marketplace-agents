"""Pulse persona — system prompt and user-facing copy builders.

Canonical voice/copy: Shop design/PULSE-PERSONA-COPY.md (Sol, P1 depth).
"""

from __future__ import annotations

import re
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

# Exact starters required by golden voice tests (PULSE-PERSONA-COPY §2 / §9).
WELCOME_STARTERS = (
    "Track OpenAI, Anthropic, and Google",
    "Pulse on Cursor and Perplexity",
    "Track Cursor and alert on Slack",
)


def module_plain(module: str) -> str:
    key = (module or "").strip().lower()
    return _MODULE_PLAIN.get(key, module or "page")


def welcome_message() -> str:
    """Greeting for chat intent (hi / empty opener). Sol §2 — no em-dashes."""
    starters = "\n".join(f"• {s}" for s in WELCOME_STARTERS)
    return (
        "I'm Competitor Pulse, a research colleague for product and GTM.\n\n"
        "I watch the public web for companies you name: site, pricing, changelog, and careers. "
        "I diff against your last baseline and write a short brief you can paste to Slack.\n\n"
        "I will not notify anyone without your OK. On the first pass I only set a baseline so "
        "later runs have something honest to compare.\n\n"
        f"Try one of these:\n{starters}\n\n"
        "Or ask what I can do."
    )


def help_message() -> str:
    """Full help / how-to reply (Sol §3a)."""
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


def help_modules() -> str:
    """Topic help: modules (Sol §3b)."""
    return (
        "I watch four public modules per competitor:\n\n"
        "• Site: homepage / product marketing pages\n"
        "• Pricing: public pricing page\n"
        "• Changelog: release notes / what's new\n"
        "• Careers: public careers / jobs page\n\n"
        "Public HTTP only. If a page is down or blocked, I say so and I do not invent content."
    )


def help_material() -> str:
    """Topic help: material bar (Sol §3c)."""
    return (
        "Material means the public page meaningfully changed vs your last baseline "
        "(new tier, headline pricing shift, notable product claim, major careers signal). "
        "Tiny crawl noise stays quiet.\n\n"
        "First run never cries material: it only sets the baseline. Later runs compare against that snapshot."
    )


def help_approve_deny() -> str:
    """Topic help: approve / deny (Sol §3d)."""
    return (
        "When notify is on and something material moved, I pause and ask.\n\n"
        "• Approve (Send notify): keep the brief; record a stub notify id in this run. "
        "v1 does not send real Slack/email.\n"
        "• Deny (Quiet: keep brief): keep the brief local; send nothing.\n\n"
        "I never contact competitors either way."
    )


def help_baselines() -> str:
    """Topic help: baselines (Sol §3e)."""
    return (
        "A baseline is the last saved public snapshot set for your watchlist.\n\n"
        "• First track: I save baselines and stay quiet (no notify ask).\n"
        "• Later track: I diff new fetches against those baselines.\n"
        "• Quiet path: nothing material moved; baselines can refresh with the same content hash "
        "without an alert.\n\n"
        "Ask me to Track … again anytime you want a fresh pass."
    )


_TOPIC_PATTERNS: list[tuple[re.Pattern[str], Any]] = [
    (
        re.compile(
            r"\b(modules?|what\s+do\s+you\s+watch|site|pricing|changelog|careers)\b",
            re.I,
        ),
        help_modules,
    ),
    (
        re.compile(
            r"\b(material|what'?s\s+material|material\s+bar|when\s+do\s+you\s+alert)\b",
            re.I,
        ),
        help_material,
    ),
    (
        re.compile(
            r"\b(approve|deny|notify\s+gate|send\s+notify|quiet:\s*keep)\b",
            re.I,
        ),
        help_approve_deny,
    ),
    (
        re.compile(r"\b(baselines?|first\s+look|first\s+run|snapshot)\b", re.I),
        help_baselines,
    ),
]


def help_for_topic(human_text: str) -> str:
    """Route help follow-ups to §3b–3e; generic help → §3a."""
    text = (human_text or "").strip()
    if not text:
        return help_message()
    # Prefer specific topic when the message is clearly about one area.
    # "what do you do" / full how-to stays on §3a unless a topic keyword dominates.
    generic = re.search(
        r"\b(what\s+do\s+you\s+do|how\s+does\s+(?:this|it)\s+work|what\s+can\s+you\s+do|"
        r"help(?:\s+me)?|getting\s+started|capabilities)\b",
        text,
        re.I,
    )
    if generic and not re.search(
        r"\b(modules?|material|approve|deny|baselines?)\b", text, re.I
    ):
        return help_message()
    for pattern, builder in _TOPIC_PATTERNS:
        if pattern.search(text):
            return builder()
    return help_message()


def other_message() -> str:
    """Ambiguous / other intent fallback."""
    return (
        "Didn't quite catch that. Want a pulse or a quick how-to?\n\n"
        "Name companies to watch (e.g. Track FedEx) or ask what I can do."
    )


def quiet_message(names: list[str], modules: list[str] | None = None) -> str:
    """Quiet-run chat line when no material changes were detected (Sol §4)."""
    _ = modules  # machine detail stays on state; not dumped in chat
    line = "Nothing material moved since your last baseline. Staying quiet."
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
    """Human-in-the-loop notify approval interrupt body (Sol §5)."""
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
    return "Got it. Staying quiet. Brief stays in this run; nothing sent."


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
    """Short pasteable notify draft (Sol §6)."""
    names_s = ", ".join(names) if names else "watchlist"
    lines = [f"Pulse: {delta_count} material change(s) on {names_s}."]
    for d in deltas[:7]:
        name = d.get("competitor") or "?"
        summary = (d.get("summary") or "").strip() or "public page moved"
        lines.append(f"- {name}: {summary}")
    return "\n".join(lines)


def human_summary_line(*, delta_count: int, names: list[str]) -> str:
    """Short prose line for logs/chat — never 'Counterposition brief ready…'."""
    names_s = ", ".join(names) if names else "watchlist"
    return f"Brief ready: {delta_count} material moves on {names_s}."


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
    """Markdown brief for material or first-look pulse runs (Sol §6 template)."""
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
        f"# Competitor pulse ({label})",
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
            # Never emit Counter/review prefixes even if a caller passes one.
            cleaned = re.sub(r"(?i)^Counter\s+\S+/\S+:\s*review\s+\S+\s*[—–-]?\s*", "", r).strip()
            if cleaned:
                lines.append(f"- {cleaned}")
    return "\n".join(lines)


def draft_task_prompt(*, deltas_json: str, run_label: str) -> str:
    """User/task prompt for optional LLM draft node (Sol §7)."""
    return (
        "Turn these material deltas into a counterposition brief a PM can paste to Slack.\n\n"
        "Rules:\n"
        "- Use ONLY the deltas and evidence URLs provided. Do not invent competitors, numbers, or pages.\n"
        "- Output markdown matching this shape:\n"
        f"  # Competitor pulse ({run_label})\n"
        "  {one-sentence thesis}\n"
        "  ## What changed\n"
        "  - **{Name}** ({module plain words}): {summary}. Evidence: {url}\n"
        "  ## How we might respond\n"
        "  - {one implication sentence each}\n"
        "- Module plain words: site → homepage / product site; pricing → pricing page; "
        "changelog → changelog / release notes; careers → careers page.\n"
        '- Never write "Counter Name/module: review change_type".\n'
        "- Never use em-dashes or double hyphens.\n"
        "- Also produce a short notify_draft (Pulse: N material change(s) on Names. + bullets).\n\n"
        f"DELTAS (JSON):\n{deltas_json}"
    )
