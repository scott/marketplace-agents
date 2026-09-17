"""Stage nodes: intake → plan → gather → analyze → draft → ask → act → report."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from competitor_pulse.chat import (
    ASSISTANT_DISPLAY_NAME,
    format_watch_ack,
    looks_like_watchlist_json,
    parse_track_message,
)
from competitor_pulse.converse import conversational_reply
from competitor_pulse.intent import classify_intent
from competitor_pulse.persona import (
    approve_stub_message,
    ask_body,
    ask_highlights,
    brief_prose,
    deny_message,
    first_look_message,
    material_chat_message,
    notify_draft_text,
    quiet_message,
    response_implication,
)
from competitor_pulse.intake_parse import parse_notify_from_message, parse_watchlist_from_message
from competitor_pulse.pulse_diff import (
    allow_network,
    default_baseline_path,
    default_fixture_dir,
    default_snapshot_dir,
    default_watchlist,
    diff_snapshots,
    load_baseline,
    load_fixture_snapshot,
    modules_from_watchlist,
    spacexai_watchlist,
    split_deltas,
)
from competitor_pulse.state import PulseState

_MODULE_KEYS = ("site", "pricing", "changelog", "careers")


def _append_summary(state: PulseState, line: str) -> list[str]:
    prev = list(state.get("stage_summaries") or [])
    prev.append(line)
    return prev


def _normalize_decision(raw: Any) -> str:
    """Primary: approve|deny strings. Optional legacy dict compat (undocumented)."""
    if isinstance(raw, dict):
        if "approved" in raw:
            return "approve" if raw.get("approved") else "deny"
        raw = raw.get("decision") or raw.get("value") or "deny"
    decision_s = str(raw).strip().lower()
    if decision_s not in {"approve", "deny"}:
        return "deny"
    return decision_s


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _assistant_reply(summary: str, brief_md: str | None = None) -> dict[str, Any]:
    """Build the final assistant-visible chat message for Agent Server / MARS UI."""
    content = summary
    if brief_md:
        content = f"{summary}\n\n---\n\n{brief_md}"
    return {
        "messages": [
            AIMessage(content=content, name=ASSISTANT_DISPLAY_NAME),
        ]
    }


def _watch_names_from(watchlist: list[dict[str, Any]] | None) -> list[str]:
    return [
        (item.get("name") or "").strip() or "?"
        for item in (watchlist or [])
        if (item.get("name") or "").strip()
    ]


def _competitors_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Accept legacy ``watchlist`` or ``competitors`` keys from JSON intake."""
    for key in ("competitors", "watchlist"):
        val = payload.get(key)
        if isinstance(val, list):
            return list(val)
    return None


def _state_competitors(state: PulseState | dict[str, Any]) -> list[dict[str, Any]]:
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


def _competitors_update(
    state: PulseState | dict[str, Any],
    competitors: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Nest non-empty competitors under ``internal``; omit key when empty."""
    wl = list(competitors or [])
    if not wl:
        return {}
    internal = dict(state.get("internal") or {})
    internal["competitors"] = wl
    return {"internal": internal}


def _competitors_from_update(full: dict[str, Any]) -> list[dict[str, Any]]:
    internal = full.get("internal")
    if isinstance(internal, dict):
        for key in ("competitors", "watchlist"):
            wl = internal.get(key)
            if isinstance(wl, list):
                return list(wl)
    for key in ("competitors", "watchlist"):
        legacy = full.get(key)
        if isinstance(legacy, list):
            return list(legacy)
    return []


def _mars_stream_safe_update(full: dict[str, Any]) -> dict[str, Any]:
    """Drop internal/competitors keys from node stream updates."""
    return {
        key: value
        for key, value in full.items()
        if key not in {"watchlist", "competitors", "internal"}
    }


def _mars_safe_pulse_update(state: dict[str, Any]) -> dict[str, Any]:
    """Expose pulse results to MARS without raw competitors JSON in stream updates."""
    watchlist = _state_competitors(state)
    out: dict[str, Any] = {
        "watch_names": _watch_names_from(watchlist),
    }
    passthrough = (
        "chat_ack",
        "notify",
        "channel",
        "fixture_dir",
        "baseline_path",
        "snapshot_dir",
        "allow_net",
        "status",
        "modules",
        "run_id",
        "snapshots",
        "deltas",
        "baseline_captures",
        "material",
        "first_run",
        "brief_md",
        "counterpositions",
        "delta_count",
        "notify_draft",
        "skipped",
        "notified",
        "stage_summaries",
        "blocked_reason",
    )
    for key in passthrough:
        if key in state:
            out[key] = state[key]
    return out


def _mars_safe_intake_update(full: dict[str, Any]) -> dict[str, Any]:
    """Strip internal competitors from intake stream updates; keep watch_names."""
    watchlist = _competitors_from_update(full)
    out = _mars_stream_safe_update(full)
    if watchlist or full.get("intent") == "pulse":
        out["watch_names"] = _watch_names_from(watchlist)
    return out


def _human_message_text(messages: list[Any] | None) -> str:
    for msg in reversed(messages or []):
        if isinstance(msg, HumanMessage):
            content = msg.content
            return content if isinstance(content, str) else str(content)
        if isinstance(msg, dict):
            role = (msg.get("type") or msg.get("role") or "").lower()
            if role in {"human", "user"}:
                return str(msg.get("content") or "")
    return ""


def _parse_intake_json(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None

    fence = re.search(
        r"```(?:json)?\s*\n?(.*?)\n?```",
        stripped,
        re.DOTALL | re.IGNORECASE,
    )
    if fence:
        try:
            parsed = json.loads(fence.group(1).strip())
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    brace = re.search(r"\{.*\}", stripped, re.DOTALL)
    if brace:
        try:
            parsed = json.loads(brace.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return None


def _apply_intake_overlay(state: PulseState, payload: dict[str, Any]) -> dict[str, Any]:
    """Overlay JSON keys onto intake fields when state lacks them."""
    out: dict[str, Any] = {}

    state_competitors = _state_competitors(state)
    payload_competitors = _competitors_from_payload(payload)
    if not state_competitors and payload_competitors:
        out["competitors"] = payload_competitors

    if "notify" not in state and "notify" in payload:
        out["notify"] = bool(payload.get("notify"))

    if "allow_net" not in state and "allow_net" in payload:
        out["allow_net"] = bool(payload.get("allow_net"))

    state_channel = (state.get("channel") or "").strip()
    payload_channel = payload.get("channel")
    if not state_channel and isinstance(payload_channel, str) and payload_channel.strip():
        out["channel"] = payload_channel.strip()

    if "preset" in payload:
        out["preset"] = str(payload.get("preset") or "").strip()

    for path_key in ("baseline_path", "snapshot_dir", "fixture_dir"):
        state_path = (state.get(path_key) or "").strip()
        payload_path = payload.get(path_key)
        if not state_path and isinstance(payload_path, str) and payload_path.strip():
            out[path_key] = payload_path.strip()

    return out


def _resolve_competitors(
    state: PulseState,
    overlay: dict[str, Any],
    human_text: str,
) -> dict[str, Any]:
    """Resolve competitor list with source metadata for intake defaults."""
    overlay_list = overlay.get("competitors") or overlay.get("watchlist")
    watchlist = list(overlay_list or _state_competitors(state))
    if watchlist:
        return {"competitors": watchlist, "from_nl": False, "blocked": False}

    preset = (overlay.get("preset") or "").strip().lower()
    if preset == "spacexai" or "SPACEXAI_PRESET" in human_text:
        return {
            "competitors": spacexai_watchlist(),
            "from_nl": False,
            "blocked": False,
        }

    parsed = parse_watchlist_from_message(human_text)
    nl_competitors = list(
        parsed.get("competitors") or parsed.get("watchlist") or []
    )
    if nl_competitors:
        return {
            "competitors": nl_competitors,
            "from_nl": True,
            "blocked": False,
            "notify": parsed.get("notify"),
            "source": parsed.get("source"),
        }

    if parsed.get("is_tracking_request") and not parsed.get("is_generic"):
        fallback = parse_track_message(human_text)
        if fallback:
            return {
                "competitors": fallback,
                "from_nl": True,
                "blocked": False,
                "notify": parsed.get("notify"),
                "source": "offline",
            }
        return {
            "competitors": [],
            "from_nl": True,
            "blocked": True,
            "notify": parsed.get("notify"),
            "blocked_summary": (
                "Could not resolve companies to track. "
                "Please name specific competitors (e.g. OpenAI, Anthropic, Cursor)."
            ),
        }

    if not human_text.strip():
        return {
            "competitors": default_watchlist(),
            "from_nl": False,
            "blocked": False,
        }

    return {
        "competitors": [],
        "from_nl": False,
        "blocked": False,
    }


def _delta_bullet(d: dict[str, Any]) -> str:
    comp = d.get("competitor") or "?"
    module = d.get("module") or "?"
    summary = d.get("summary") or ""
    url = d.get("evidence_url") or ""
    line = f"- **{comp}** ({module}): {summary}"
    if url:
        line += f" — {url}"
    return line


# ---------------------------------------------------------------------------
# intake
# ---------------------------------------------------------------------------


def intake(state: PulseState) -> dict[str, Any]:
    if state.get("force_blocked"):
        update: dict[str, Any] = {
            "status": "blocked",
            "notify": bool(state.get("notify")),
            "blocked_reason": "Blocked: fetch/tools unavailable.",
            "stage_summaries": _append_summary(
                state, "intake: blocked — fetch/tools unavailable"
            ),
            "deltas": [],
            "material": False,
            "skipped": False,
        }
        update.update(_competitors_update(state, _state_competitors(state)))
        return update

    human_text = _human_message_text(state.get("messages"))
    if not human_text.strip():
        human_text = (state.get("user_message") or "").strip()

    # Parse structured JSON payloads silently — never echo raw JSON in chat.
    intake_json = _parse_intake_json(human_text) if human_text else None
    overlay = _apply_intake_overlay(state, intake_json or {})
    nl_text = "" if looks_like_watchlist_json(human_text) else human_text

    parsed_nl = parse_watchlist_from_message(nl_text) if nl_text else {}
    overlay_competitors = _competitors_from_payload(overlay) if overlay else None
    intent = classify_intent(
        nl_text,
        state_watchlist=_state_competitors(state),
        overlay_watchlist=overlay_competitors,
        overlay_preset=overlay.get("preset"),
        parsed_nl=parsed_nl,
    )

    if intent in {"chat", "help", "other"}:
        # Single-node chat path (diag-shaped): emit AIMessage here and route to END.
        # No empty list fields (deltas/artifacts) — those JSON-serialize into doctl text.
        # No second converse node (prod doubled greetings via stream+final).
        reply = conversational_reply(intent, human_text or "")
        return {
            "intent": intent,
            "status": intent,
            "material": False,
            "skipped": False,
            "notified": False,
            **_assistant_reply(reply, None),
        }

    resolved = _resolve_competitors(state, overlay, nl_text)
    watchlist = list(resolved.get("competitors") or [])
    from_nl = bool(resolved.get("from_nl"))

    if resolved.get("blocked"):
        blocked_summary = resolved.get("blocked_summary") or (
            "Could not resolve companies to track."
        )
        return {
            "status": "blocked",
            "notify": False,
            "blocked_reason": blocked_summary,
            "stage_summaries": _append_summary(
                state, f"intake: blocked — {blocked_summary}"
            ),
            "deltas": [],
            "material": False,
            "skipped": False,
        }

    if "notify" in overlay:
        notify = bool(overlay.get("notify"))
    elif "notify" in state:
        notify = bool(state.get("notify"))
    elif resolved.get("notify") is not None:
        notify = bool(resolved.get("notify"))
    elif nl_text.strip():
        notify = bool(parse_notify_from_message(nl_text) or False)
    else:
        notify = False

    channel = (
        overlay.get("channel")
        or (state.get("channel") or "slack").strip()
        or "slack"
    )
    fixture_dir = (state.get("fixture_dir") or "").strip() or str(
        default_fixture_dir()
    )
    baseline_path = (state.get("baseline_path") or "").strip() or str(
        default_baseline_path()
    )
    snapshot_dir = (state.get("snapshot_dir") or "").strip() or str(
        default_snapshot_dir()
    )
    if "allow_net" in overlay:
        allow_net = bool(overlay.get("allow_net"))
    elif "allow_net" in state:
        allow_net = bool(state.get("allow_net"))
    elif from_nl:
        allow_net = True
    else:
        allow_net = allow_network()

    from_chat = bool(from_nl or nl_text.strip())
    chat_ack = format_watch_ack(
        watchlist, allow_net=allow_net, from_chat=from_chat
    )
    return {
        "intent": "pulse",
        **_competitors_update(state, watchlist),
        "notify": notify,
        "channel": channel,
        "fixture_dir": fixture_dir,
        "baseline_path": baseline_path,
        "snapshot_dir": snapshot_dir,
        "allow_net": allow_net,
        "status": "ok",
        "chat_ack": chat_ack,
        "first_run": False,
        "stage_summaries": _append_summary(state, "intake: watchlist ready"),
        "skipped": False,
        "notified": False,
        "deltas": [],
        "material": False,
    }


def intake_node(state: PulseState) -> dict[str, Any]:
    """Graph intake: classify/route without streaming raw watchlist JSON."""
    return _mars_safe_intake_update(intake(state))


def execute_pulse(state: PulseState) -> dict[str, Any]:
    """Run plan→draft as one streamed node; restore watchlist internally."""
    current: dict[str, Any] = dict(state)
    if current.get("intent") == "pulse" and not _state_competitors(current):
        current.update(intake(state))
    for stage in (plan, gather, analyze, draft):
        update = stage(current)  # type: ignore[arg-type]
        if update:
            current.update(update)
    return _mars_safe_pulse_update(current)


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------


def plan(state: PulseState) -> dict[str, Any]:
    if state.get("status") == "blocked":
        return {}

    watchlist = _state_competitors(state)
    modules = modules_from_watchlist(watchlist)
    run_id = f"pulse-{uuid.uuid4().hex[:10]}"
    return {
        "modules": modules,
        "run_id": run_id,
        "stage_summaries": _append_summary(
            state, f"plan: modules={','.join(modules)}"
        ),
    }


# ---------------------------------------------------------------------------
# gather
# ---------------------------------------------------------------------------


def _fetch_http(url: str) -> dict[str, Any] | None:
    try:
        import httpx

        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url)
            text = resp.text or ""
            ok = 200 <= resp.status_code < 400
            from competitor_pulse.pulse_diff import content_hash

            return {
                "text": text,
                "content_hash": content_hash(text),
                "ok": ok,
                "source": "http",
                "status_code": resp.status_code,
            }
    except Exception as exc:  # noqa: BLE001 — gather continues on per-URL fail
        return {
            "text": "",
            "content_hash": "",
            "ok": False,
            "source": "http",
            "error": str(exc)[:200],
        }


def gather(state: PulseState) -> dict[str, Any]:
    if state.get("status") == "blocked":
        return {}

    watchlist = _state_competitors(state)
    snapshot_dir = Path(state.get("snapshot_dir") or default_snapshot_dir())
    allow_net = bool(state.get("allow_net"))
    fetched_at = _now_iso()
    snapshots: list[dict[str, Any]] = []

    for item in watchlist:
        name = (item.get("name") or "").strip() or "Unknown"
        urls = item.get("urls") or {}
        for module in _MODULE_KEYS:
            url = urls.get(module)
            if not url:
                continue
            snap: dict[str, Any] | None = None
            if not allow_net:
                snap = load_fixture_snapshot(snapshot_dir, name, module)
                if snap:
                    snap = {
                        **snap,
                        "url": url,
                        "fetched_at": fetched_at,
                    }
            else:
                http_result = _fetch_http(url)
                if http_result and http_result.get("ok"):
                    snap = {
                        "competitor": name,
                        "module": module,
                        "url": url,
                        "fetched_at": fetched_at,
                        **http_result,
                    }
                else:
                    snap = load_fixture_snapshot(snapshot_dir, name, module)
                    if snap:
                        snap = {
                            **snap,
                            "url": url,
                            "fetched_at": fetched_at,
                            "source": "fixture_fallback",
                        }
                    else:
                        snap = {
                            "competitor": name,
                            "module": module,
                            "url": url,
                            "fetched_at": fetched_at,
                            "ok": False,
                            "text": "",
                            "content_hash": "",
                            "source": "http",
                            "error": (http_result or {}).get("error")
                            or "fetch failed",
                        }
            if snap is None:
                snapshots.append(
                    {
                        "competitor": name,
                        "module": module,
                        "url": url,
                        "fetched_at": fetched_at,
                        "ok": False,
                        "text": "",
                        "content_hash": "",
                        "source": "missing",
                    }
                )
            else:
                snapshots.append(snap)

    ok_n = sum(1 for s in snapshots if s.get("ok"))
    fail_n = len(snapshots) - ok_n
    out: dict[str, Any] = {
        "snapshots": snapshots,
        "stage_summaries": _append_summary(
            state, f"gather: fetched {ok_n} ok, {fail_n} failed"
        ),
    }
    if not snapshots:
        out["status"] = "blocked"
        out["stage_summaries"] = _append_summary(
            state, "gather: blocked — no snapshots"
        )
    return out


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


def analyze(state: PulseState) -> dict[str, Any]:
    if state.get("status") == "blocked":
        return {}

    if state.get("force_empty"):
        return {
            "deltas": [],
            "baseline_captures": [],
            "material": False,
            "first_run": False,
            "status": "empty",
            "stage_summaries": _append_summary(
                state, "analyze: empty (forced)"
            ),
        }

    baseline_path = Path(state.get("baseline_path") or default_baseline_path())
    baseline_index = load_baseline(baseline_path)
    snapshots = list(state.get("snapshots") or [])
    all_deltas = diff_snapshots(snapshots, baseline_index)
    captures, changes = split_deltas(all_deltas)

    if state.get("force_material") and not changes:
        changes = [
            {
                "competitor": "Acme",
                "module": "pricing",
                "change_type": "pricing_change",
                "summary": "Pricing page updated — test fixture.",
                "evidence_url": "https://example.com/acme/pricing",
                "old_hash": "old",
                "new_hash": "forced",
                "is_baseline_capture": False,
            }
        ]

    first_run = bool(captures) and not changes
    material = bool(changes)

    if not all_deltas:
        return {
            "deltas": [],
            "baseline_captures": [],
            "material": False,
            "first_run": False,
            "status": "empty",
            "stage_summaries": _append_summary(state, "analyze: no changes"),
        }

    if first_run:
        return {
            "deltas": captures,
            "baseline_captures": captures,
            "material": False,
            "first_run": True,
            "status": "baseline",
            "stage_summaries": _append_summary(
                state, f"analyze: baseline established ({len(captures)} pages)"
            ),
        }

    return {
        "deltas": changes,
        "baseline_captures": captures,
        "material": material,
        "first_run": False,
        "status": "ok" if material else "empty",
        "stage_summaries": _append_summary(
            state, f"analyze: {len(changes)} material change(s)"
        ),
    }


# ---------------------------------------------------------------------------
# draft
# ---------------------------------------------------------------------------


def draft(state: PulseState) -> dict[str, Any]:
    if state.get("status") in {"blocked", "empty"} and not state.get("first_run"):
        return {}

    deltas = list(state.get("deltas") or [])
    first_run = bool(state.get("first_run"))

    if not deltas and not first_run:
        return {
            "status": "empty",
            "material": False,
            "delta_count": 0,
            "stage_summaries": _append_summary(state, "draft: empty"),
        }

    delta_count = len(deltas)
    names = sorted({d.get("competitor") or "?" for d in deltas})
    gaps = list(state.get("fetch_gaps") or [])

    if first_run:
        brief_md = brief_prose(first_run=True, deltas=deltas, gaps=gaps or None)
        return {
            "brief_md": brief_md,
            "counterpositions": [],
            "delta_count": 0,
            "notify_draft": "",
            "status": "baseline",
            "stage_summaries": _append_summary(
                state, f"draft: first-look brief ({delta_count} pages)"
            ),
        }

    counterpositions = [
        line
        for d in deltas[:7]
        for line in [response_implication(d)]
        if line
    ]
    brief_md = brief_prose(
        first_run=False,
        deltas=deltas,
        counterpositions=counterpositions,
    )
    notify_draft = notify_draft_text(
        delta_count=delta_count,
        names=names,
        deltas=deltas,
    )
    return {
        "brief_md": brief_md,
        "counterpositions": counterpositions,
        "delta_count": delta_count,
        "notify_draft": notify_draft,
        "status": "ok",
        "stage_summaries": _append_summary(
            state, f"draft: brief with {delta_count} deltas"
        ),
    }



# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------


def route_after_intake(state: PulseState) -> str:
    """Chat/help/other already emitted AIMessage in intake — end (diag-shaped).

    Pulse continues to execute_pulse; blocked goes to report.
    """
    intent = (state.get("intent") or "pulse").strip().lower()
    if intent in {"chat", "help", "other"}:
        return "end"
    if state.get("status") == "blocked":
        return "report"
    return "execute_pulse"


def converse(state: PulseState) -> dict[str, Any]:
    """Single warm reply for chat / help / ambiguous — ends with one AIMessage.

    Returns only ``messages`` so doctl does not concat stream metadata with the
    final output AIMessage (observed production duplication on ``hi``).
    """
    intent = (state.get("intent") or "chat").strip().lower()
    human_text = _human_message_text(state.get("messages"))
    if not human_text.strip():
        human_text = (state.get("user_message") or "").strip()
    reply = conversational_reply(intent, human_text)
    return _assistant_reply(reply, None)


def should_ask(state: PulseState) -> str:
    """Ask only if notify requested AND material == true."""
    if state.get("status") in {"blocked", "empty", "error", "baseline"}:
        return "report"
    if state.get("first_run"):
        return "report"
    if not state.get("notify"):
        return "report"
    if not state.get("material"):
        return "report"
    if not state.get("deltas"):
        return "report"
    return "ask"


# ---------------------------------------------------------------------------
# ask / act / report
# ---------------------------------------------------------------------------


def ask(state: PulseState) -> dict[str, Any]:
    """Interrupt for human approval before notify stub."""
    from langgraph.types import interrupt

    channel = state.get("channel") or "slack"
    deltas = list(state.get("deltas") or [])
    delta_count = state.get("delta_count") or len(deltas)
    names = sorted({d.get("competitor") or "?" for d in deltas})
    highlights = ask_highlights(deltas, limit=7)
    notify_draft = state.get("notify_draft") or "(empty draft)"

    body = ask_body(
        channel=channel,
        delta_count=int(delta_count),
        names=names,
        highlights=highlights,
        notify_draft=notify_draft,
    )
    payload = {
        "title": "Notify about competitor changes?",
        "body": body,
        "pending_action": "notify",
        "channel": channel,
        "choices": ["approve", "deny"],
    }
    decision = interrupt(payload)
    decision_s = _normalize_decision(decision)
    return {
        "pending_action": "notify",
        "ask_payload": payload,
        "decision": decision_s,
        "stage_summaries": _append_summary(state, f"ask: {decision_s}"),
    }



def act(state: PulseState) -> dict[str, Any]:
    decision = _normalize_decision(state.get("decision") or "deny")
    if decision != "approve":
        return {
            "skipped": True,
            "notified": False,
            "notify_id": "",
            "status": "denied",
            "baseline_updated": False,
            "stage_summaries": _append_summary(
                state, "act: denied — no notify"
            ),
        }

    notify_id = f"stub-notify-{uuid.uuid4().hex[:8]}"
    return {
        "skipped": False,
        "notified": True,
        "notify_id": notify_id,
        "status": "notified",
        "baseline_updated": False,
        "stage_summaries": _append_summary(
            state, f"act: stub notified {notify_id}"
        ),
    }


def _format_first_run_report(state: PulseState) -> str:
    ack = state.get("chat_ack") or ""
    deltas = list(state.get("deltas") or [])
    names = sorted({d.get("competitor") or "?" for d in deltas})
    if not names:
        names = list(state.get("watch_names") or []) or _watch_names_from(
            _state_competitors(state)
        )
    gaps = list(state.get("fetch_gaps") or [])
    body = first_look_message(names, gaps=gaps or None)
    if ack:
        return f"{ack}\n\n{body}"
    return body



def _format_quiet_report(state: PulseState) -> str:
    names = list(state.get("watch_names") or [])
    if not names:
        names = _watch_names_from(_state_competitors(state))
    modules = list(state.get("modules") or [])
    body = quiet_message(names, modules)
    ack = state.get("chat_ack") or ""
    if ack:
        return f"{ack}\n\n{body}"
    return body



def _format_material_report(state: PulseState, *, notified: bool = False) -> str:
    deltas = list(state.get("deltas") or [])
    names = sorted({d.get("competitor") or "?" for d in deltas})
    if notified:
        return approve_stub_message(str(state.get("notify_id") or ""))
    if state.get("notify"):
        return material_chat_message(names, notify_off=False)
    return material_chat_message(names, notify_off=True)



def report(state: PulseState) -> dict[str, Any]:
    status = state.get("status") or "ok"
    first_run = bool(state.get("first_run"))
    material = bool(state.get("material"))
    watch_n = len(_state_competitors(state))

    if status == "blocked":
        blocked_reason = (state.get("blocked_reason") or "").strip()
        if blocked_reason:
            summary = blocked_reason
        else:
            summary = (
                "Could not complete the pulse — fetch/tools were unavailable.\n"
                f"Watchlist had {watch_n} competitor(s). Fix network/fixtures and retry."
            )
        next_hint = "Fix fixtures / network and retry."
        out_status = "blocked"
    elif first_run or status == "baseline":
        summary = _format_first_run_report(state)
        next_hint = "Re-run after competitors may have updated their pages."
        out_status = "baseline"
    elif status == "denied":
        summary = deny_message()
        next_hint = "Artifacts kept; re-run and approve to stub-notify."
        out_status = "denied"
    elif status == "notified":
        summary = approve_stub_message(str(state.get("notify_id") or ""))
        next_hint = "Review stub notify id in run state."
        out_status = "notified"
    elif material:
        summary = _format_material_report(state, notified=False)
        next_hint = "Set notify=true to gate a notify ask on the next material pulse."
        out_status = "ok"
    else:
        summary = _format_quiet_report(state)
        next_hint = "Re-run when the watchlist may have moved."
        out_status = "empty"

    artifacts = [
        a
        for a in [
            state.get("brief_md") and "brief_md",
            f"deltas:{state.get('delta_count') or len(state.get('deltas') or [])}",
            state.get("notify_id") or "",
            state.get("run_id") or "",
        ]
        if a
    ]

    return {
        "status": out_status,
        "artifacts": artifacts,
        "next_hint": next_hint,
        "stage_summaries": _append_summary(state, "report: complete"),
        **_assistant_reply(summary, state.get("brief_md") or None),
    }
