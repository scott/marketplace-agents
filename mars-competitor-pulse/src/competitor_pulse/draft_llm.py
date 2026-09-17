"""Optional LLM synthesis for material counterposition briefs (Sol §7).

Diffs stay deterministic in gather/analyze. Default path is template-only:
MARS/doctl concatenates harness ``llm.invoke`` token streams into prompt
``text`` (same failure mode as watchlist parse / converse). Enable LLM draft
only via ``COMPETITOR_PULSE_LLM_DRAFT=1`` (off by default), never on the chat
path.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from typing import Any

from competitor_pulse.hygiene import hygiene_text
from competitor_pulse.persona import (
    PULSE_SYSTEM_PROMPT,
    brief_prose,
    draft_task_prompt,
    human_summary_line,
    notify_draft_text,
    response_implication,
)


def llm_draft_enabled() -> bool:
    flag = (os.environ.get("COMPETITOR_PULSE_LLM_DRAFT") or "").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def template_material_draft(
    deltas: list[dict[str, Any]],
    *,
    run_label: str | None = None,
) -> dict[str, Any]:
    """Sol §6 / §7 template fallback — no LLM, no stream leak."""
    names = sorted({str(d.get("competitor") or "?") for d in deltas})
    counterpositions = [
        line
        for d in deltas[:7]
        for line in [response_implication(d)]
        if line
    ]
    brief_md = hygiene_text(
        brief_prose(
            first_run=False,
            deltas=deltas,
            counterpositions=counterpositions,
            run_label=run_label,
        )
    )
    notify_draft = hygiene_text(
        notify_draft_text(
            delta_count=len(deltas),
            names=names,
            deltas=deltas,
        )
    )
    return {
        "brief_md": brief_md,
        "counterpositions": [hygiene_text(c) for c in counterpositions],
        "notify_draft": notify_draft,
        "human_summary": hygiene_text(
            human_summary_line(delta_count=len(deltas), names=names)
        ),
        "draft_source": "template",
    }


def _parse_llm_brief(content: str) -> dict[str, str] | None:
    """Extract brief_md + optional notify_draft from model text."""
    text = (content or "").strip()
    if not text:
        return None
    fence = re.search(r"```(?:markdown|md)?\s*\n?(.*?)\n?```", text, re.DOTALL | re.I)
    body = fence.group(1).strip() if fence else text

    notify = ""
    notify_m = re.search(
        r"(?is)(?:notify[_ ]?draft\s*:?\s*)(Pulse:\s*.+?)(?:\n\n|\Z)",
        body,
    )
    if notify_m:
        notify = notify_m.group(1).strip()
        body = body[: notify_m.start()].strip()
    else:
        pulse_m = re.search(r"(?m)^(Pulse:\s.+)$", body)
        if pulse_m:
            # Trailing Pulse block after the markdown brief.
            after = body[pulse_m.start() :]
            if "## How we might respond" in body[: pulse_m.start()] or body.strip().startswith("#"):
                notify = after.strip()
                body = body[: pulse_m.start()].strip()

    if not body.lstrip().startswith("#") and "What changed" not in body:
        return None
    return {"brief_md": body, "notify_draft": notify}


def _implications_from_brief(brief_md: str) -> list[str]:
    lines: list[str] = []
    in_section = False
    for line in brief_md.splitlines():
        if re.match(r"^##\s+How we might respond", line, re.I):
            in_section = True
            continue
        if in_section and re.match(r"^##\s+", line):
            break
        if in_section:
            m = re.match(r"^[-*]\s+(.+)$", line.strip())
            if m:
                lines.append(m.group(1).strip())
    return lines


def llm_material_draft(
    deltas: list[dict[str, Any]],
    *,
    run_label: str | None = None,
) -> dict[str, Any] | None:
    """Invoke LLM under PULSE_SYSTEM_PROMPT. Returns None on any failure.

    Callers must only use this when ``llm_draft_enabled()`` is True. Even then,
    enabling on MARS risks token-stream concat into doctl ``text``.
    """
    try:
        from competitor_pulse.llm import get_llm, harness_env_available

        if not harness_env_available():
            return None

        label = run_label or date.today().isoformat()
        deltas_json = json.dumps(deltas, ensure_ascii=False, indent=2)
        task = draft_task_prompt(deltas_json=deltas_json, run_label=label)
        llm = get_llm(temperature=0)
        # Prefer non-streaming invoke; never return raw response to graph stream.
        messages = [
            {"role": "system", "content": PULSE_SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]
        response = llm.invoke(messages)
        content = getattr(response, "content", "") or ""
        if isinstance(content, list):
            content = " ".join(
                part.get("text", str(part)) if isinstance(part, dict) else str(part)
                for part in content
            )
        parsed = _parse_llm_brief(str(content))
        if not parsed:
            return None

        names = sorted({str(d.get("competitor") or "?") for d in deltas})
        brief_md = hygiene_text(parsed["brief_md"])
        # Hard reject if kill-list labels survived.
        if "review site_copy_change" in brief_md or "Counter " in brief_md:
            return None
        notify_draft = hygiene_text(
            parsed.get("notify_draft")
            or notify_draft_text(
                delta_count=len(deltas), names=names, deltas=deltas
            )
        )
        counterpositions = _implications_from_brief(brief_md)
        if not counterpositions:
            counterpositions = [
                line
                for d in deltas[:7]
                for line in [response_implication(d)]
                if line
            ]
        return {
            "brief_md": brief_md,
            "counterpositions": [hygiene_text(c) for c in counterpositions],
            "notify_draft": notify_draft,
            "human_summary": hygiene_text(
                human_summary_line(delta_count=len(deltas), names=names)
            ),
            "draft_source": "llm",
        }
    except Exception:
        return None


def synthesize_material_draft(
    deltas: list[dict[str, Any]],
    *,
    run_label: str | None = None,
) -> dict[str, Any]:
    """Template by default; optional LLM when COMPETITOR_PULSE_LLM_DRAFT=1."""
    if llm_draft_enabled():
        llm_out = llm_material_draft(deltas, run_label=run_label)
        if llm_out:
            return llm_out
    return template_material_draft(deltas, run_label=run_label)
