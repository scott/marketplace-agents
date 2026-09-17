"""Final state exposes assistant-visible AIMessage for Agent Server / MARS UI."""

from __future__ import annotations

import json
import re

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from competitor_pulse.chat import contains_watchlist_json
from competitor_pulse.graph import compile_graph
from competitor_pulse.mars_text import (
    assemble_doctl_prompt_text,
    hi_chat_payload,
    strip_doctl_artifacts,
)
from competitor_pulse.pulse_diff import (
    default_baseline_path,
    default_watchlist,
    material_baseline_path,
    quiet_baseline_path,
)

from pulse_helpers import assistant_summary, default_pulse_payload, invoke_graph

_WATCHLIST_JSON_RE = re.compile(r'\{\s*"watchlist"\s*:', re.IGNORECASE)


def _offline(monkeypatch):
    monkeypatch.delenv("HARNESS_INFERENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ALLOW_NET", "0")


def _ai_messages(result: dict) -> list[AIMessage]:
    return [m for m in (result.get("messages") or []) if isinstance(m, AIMessage)]


def _last_ai_message(result: dict) -> AIMessage:
    msgs = _ai_messages(result)
    assert msgs, "expected at least one assistant message in final state"
    return msgs[-1]


def test_quiet_run_emits_assistant_message(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    result = invoke_graph(
        g,
        default_pulse_payload(
            notify=True,
            baseline_path=str(quiet_baseline_path()),
        ),
    )
    ai = _last_ai_message(result)
    content = ai.content.lower()
    assert "no changes" in content or "no material" in content or "nothing material" in content
    assert ai.content == assistant_summary(result)


def test_material_notify_off_includes_brief(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    result = invoke_graph(
        g,
        default_pulse_payload(baseline_path=str(material_baseline_path())),
    )
    ai = _last_ai_message(result)
    assert "competitor pulse" in ai.content.lower()
    assert result.get("brief_md")
    assert result["brief_md"] in ai.content
    assert ai.content.startswith(assistant_summary(result))


def test_resume_approve_emits_assistant_message(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "messages-approve"}}
    mid = invoke_graph(
        g,
        default_pulse_payload(
            notify=True,
            baseline_path=str(default_baseline_path()),
        ),
        cfg,
    )
    assert "__interrupt__" in mid

    final = g.invoke(Command(resume="approve"), cfg)
    ai = _last_ai_message(final)
    assert final.get("status") == "notified"
    assert "notify sent" in ai.content.lower() or "stub notify" in ai.content.lower()
    assert final.get("brief_md") in ai.content


def test_hi_chat_emits_exactly_one_assistant_message(monkeypatch):
    """Greeting path must not duplicate intake ack + report in messages[]."""
    _offline(monkeypatch)
    g = compile_graph()
    result = g.invoke(
        {
            "messages": [HumanMessage(content="hi")],
            "allow_net": False,
        }
    )
    assert len(_ai_messages(result)) == 1
    ai = _last_ai_message(result)
    assert isinstance(ai.content, str)
    assert not contains_watchlist_json(ai.content)


def test_no_assistant_message_contains_watchlist_json(monkeypatch):
    """Chat bubbles must never include raw watchlist JSON."""
    _offline(monkeypatch)
    g = compile_graph()
    cases = [
        {"messages": [HumanMessage(content="hi")], "allow_net": False},
        {"messages": [HumanMessage(content="track fedex")], "allow_net": False},
        default_pulse_payload(baseline_path=str(material_baseline_path())),
    ]
    for payload in cases:
        result = invoke_graph(g, payload)
        for ai in _ai_messages(result):
            content = ai.content if isinstance(ai.content, str) else str(ai.content)
            assert not _WATCHLIST_JSON_RE.search(content)
            assert not contains_watchlist_json(content)


def test_stream_updates_never_include_watchlist(monkeypatch):
    """MARS streams node updates — no node may emit watchlist JSON."""
    _offline(monkeypatch)
    g = compile_graph()
    for chunk in g.stream(
        {"messages": [HumanMessage(content="track fedex")], "allow_net": False},
        stream_mode="updates",
    ):
        for _node, update in chunk.items():
            assert "watchlist" not in (update or {})
            assert "competitors" not in (update or {})
            assert "internal" not in (update or {})
            assert "converse_reply" not in (update or {})
            if update and update.get("messages"):
                for msg in update["messages"]:
                    if isinstance(msg, AIMessage):
                        content = msg.content if isinstance(msg.content, str) else str(
                            msg.content
                        )
                        assert not contains_watchlist_json(content)


def test_hi_stream_has_no_watchlist_or_duplicate_messages(monkeypatch):
    """Greeting path streams conversational update only — one final AIMessage."""
    _offline(monkeypatch)
    g = compile_graph()
    ai_count = 0
    for chunk in g.stream(
        {"messages": [HumanMessage(content="hi")], "allow_net": False},
        stream_mode="updates",
    ):
        for _node, update in chunk.items():
            assert "watchlist" not in (update or {})
            assert "competitors" not in (update or {})
            assert "internal" not in (update or {})
            assert "converse_reply" not in (update or {})
            if update and update.get("messages"):
                ai_count += sum(
                    1 for msg in update["messages"] if isinstance(msg, AIMessage)
                )
    assert ai_count == 1


def test_graph_compile_name(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    assert g.name == "Competitor Pulse"


def test_doctl_shaped_hi_text_clean(monkeypatch):
    """Production doctl ``text``: no watchlist JSON prefix, greeting once after strip."""
    _offline(monkeypatch)
    g = compile_graph()
    text = strip_doctl_artifacts(assemble_doctl_prompt_text(g, hi_chat_payload()))
    assert not contains_watchlist_json(text)
    assert text.count("Competitor Pulse") >= 1
    assert text.index("Competitor Pulse") == text.rindex("Competitor Pulse")
