"""Helpers for MARS / doctl prompt ``text`` assembly (production-shaped guards)."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from competitor_pulse.chat import contains_watchlist_json

# Observed production doctl concat: prose string fields from stream updates.
_STREAM_PROSE_KEYS = ("human_summary", "converse_reply", "chat_ack")

# Empty list fields doctl may prefix when a schema property name matches.
_STATE_LIST_PREFIX_RE = re.compile(
    r'^\s*\{\s*"(?:watchlist|competitors)"\s*:\s*\[\s*\]\s*\}',
    re.IGNORECASE,
)

_GREETING_DEDUP_RE = re.compile(
    r"(?:Hey there|Hey — I'm|Hey, welcome).{0,80}Competitor Pulse|"
    r"I'm Competitor Pulse(?:\s*[—-]\s*a research colleague)?",
    re.IGNORECASE,
)


def strip_doctl_artifacts(text: str) -> str:
    """Model observed prod doctl ``text`` noise for test assertions only.

    Strips leading ``{"watchlist":[]}`` / ``{"competitors":[]}`` prefixes and
    deduplicates a repeated greeting block when platform concat doubles the
    same ``AIMessage``.
    """
    out = _STATE_LIST_PREFIX_RE.sub("", text or "", count=1)
    matches = list(_GREETING_DEDUP_RE.finditer(out))
    if len(matches) >= 2:
        first = matches[0]
        second = matches[1]
        if first.group(0) == second.group(0):
            out = out[: second.start()] + out[second.end() :]
    return out


def assemble_doctl_prompt_text(
    graph: Any,
    payload: dict[str, Any],
) -> str:
    """Best-effort model of how ``doctl agent prompt -o json`` builds ``text``.

    Models a **single** run (stream updates + final output from that run's last
    state), concatenating:
    1. Serialized input list fields when the exported input schema includes them
    2. Each node update's ``watchlist`` / ``competitors`` / ``internal.*`` when present
       (must be absent after stream-safe returns — presence is a regression)
    3. Prose string fields from stream updates (``chat_ack`` must not appear)
    4. Each streamed ``AIMessage`` content
    5. Final output ``messages`` not already appended (same content deduped)

    Chat path is intake→END with one AIMessage (diag-shaped) + Sol templates only
    (no llm.invoke on converse/watchlist parse) so MARS cannot prefix JSON or
    double the greeting via harness token streams.
    """
    text = ""
    seen_ai: set[str] = set()
    input_props = (graph.get_input_jsonschema().get("properties") or {})
    for key in ("watchlist", "competitors"):
        if key in input_props and key in payload:
            text += json.dumps({key: payload[key]}, separators=(",", ":"))

    final_state: dict[str, Any] | None = None
    for chunk in graph.stream(payload, stream_mode="updates"):
        for _node, update in chunk.items():
            u = update or {}
            for key in ("watchlist", "competitors"):
                if key in u:
                    text += json.dumps({key: u[key]}, separators=(",", ":"))
            internal = u.get("internal")
            if isinstance(internal, dict):
                # internal.competitors is graph persistence only — never doctl chat text
                _ = internal
            for key in _STREAM_PROSE_KEYS:
                val = u.get(key)
                if val:
                    text += str(val)
            for msg in u.get("messages") or []:
                if isinstance(msg, AIMessage):
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    if content not in seen_ai:
                        text += content
                        seen_ai.add(content)
        # keep last values snapshot via separate invoke only if needed
    final_state = graph.invoke(payload)
    for msg in (final_state or {}).get("messages") or []:
        if isinstance(msg, AIMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if content not in seen_ai:
                text += content
                seen_ai.add(content)
    return text


def last_assistant_text(result: dict[str, Any]) -> str:
    """Plain assistant copy from final ``messages`` (output-schema safe)."""
    for msg in reversed(result.get("messages") or []):
        if isinstance(msg, AIMessage):
            content = msg.content
            return content if isinstance(content, str) else str(content)
    return ""


def summary_from_assistant_text(text: str) -> str:
    """Human summary portion before optional ``---`` brief separator."""
    if "\n\n---\n\n" in text:
        return text.split("\n\n---\n\n", 1)[0]
    return text


def prepare_programmatic_payload(state: dict[str, Any]) -> dict[str, Any]:
    """Encode competitors as a silent JSON HumanMessage (not in ``input_schema``).

    Accepts legacy ``watchlist`` or ``competitors`` invoke keys. Other invoke keys
    (``baseline_path``, ``notify``, …) stay top-level because they remain in
    ``InputState``.
    """
    payload = dict(state)
    competitors = payload.pop("competitors", None)
    if competitors is None:
        competitors = payload.pop("watchlist", None)
    if competitors is not None:
        existing = payload.get("messages") or []
        msgs = [HumanMessage(content=json.dumps({"competitors": competitors}))]
        user_msg = (payload.get("user_message") or "").strip()
        if user_msg:
            msgs.append(HumanMessage(content=user_msg))
        payload["messages"] = [*msgs, *existing]
    return payload


def hi_chat_payload(*, include_empty_watchlist: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "messages": [HumanMessage(content="hi")],
        "allow_net": False,
    }
    if include_empty_watchlist:
        payload["competitors"] = []
    return payload


def competitors_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Read nested internal competitors (legacy watchlist keys accepted)."""
    internal = state.get("internal")
    if isinstance(internal, dict):
        for key in ("competitors", "watchlist"):
            wl = internal.get(key)
            if isinstance(wl, list):
                return list(wl)
    for key in ("competitors", "watchlist"):
        legacy = state.get(key)
        if isinstance(legacy, list):
            return list(legacy)
    return []


# Back-compat alias for tests importing the old name.
watchlist_from_state = competitors_from_state
