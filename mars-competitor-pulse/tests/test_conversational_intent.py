"""Conversational intent routing: chat, help, no Acme fixture fallback."""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage

from competitor_pulse.graph import compile_graph
from competitor_pulse.intent import classify_intent, is_chat_message, is_help_message
from competitor_pulse.nodes import intake
from competitor_pulse.pulse_diff import default_watchlist

from pulse_helpers import assistant_summary, invoke_graph, invoke_graph_full, watchlist_from_state


def _offline(monkeypatch):
    monkeypatch.delenv("HARNESS_INFERENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ALLOW_NET", "0")


def test_classify_chat_and_help():
    assert classify_intent("hi") == "chat"
    assert classify_intent("run") == "chat"
    assert classify_intent("thanks!") == "chat"
    assert classify_intent("what do you do?") == "help"
    assert classify_intent("how does this work") == "help"
    assert classify_intent("track fedex") == "pulse"
    assert classify_intent("") == "pulse"
    assert is_chat_message("hey there") is False  # not exact generic
    assert is_help_message("tell me about baselines") is True


def test_intake_hi_is_chat_not_acme(monkeypatch):
    _offline(monkeypatch)
    result = intake({"messages": [HumanMessage(content="hi")]})
    assert result.get("intent") == "chat"
    assert watchlist_from_state(result) == []
    assert "watchlist" not in result
    assert "competitors" not in result
    assert "internal" not in result


def test_intake_no_message_still_fixture_watchlist(monkeypatch):
    """Programmatic invoke without chat text keeps fixture path."""
    _offline(monkeypatch)
    result = intake({})
    assert result.get("intent") == "pulse"
    assert watchlist_from_state(result) == default_watchlist()


def test_hi_greeting_full_graph(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    result = invoke_graph_full(g, {"messages": [HumanMessage(content="hi")]})
    summary = assistant_summary(result)
    assert result.get("status") == "chat"
    assert result.get("material") is False
    assert not result.get("deltas")
    assert "Acme" not in summary
    assert "Competitor Pulse" in summary
    assert "track" in summary.lower()
    # Sol P0: welcome must promise no notify without OK
    assert "without your ok" in summary.lower() or "without your approval" in summary.lower() or "will not notify" in summary.lower()
    summaries = " ".join(result.get("stage_summaries") or [])
    assert "gather:" not in summaries
    assert "analyze:" not in summaries


def test_help_question_full_graph(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    result = g.invoke(
        {"messages": [HumanMessage(content="what do you do?")]}
    )
    summary = assistant_summary(result)
    assert result.get("status") == "help"
    assert result.get("material") is False
    assert "baseline" in summary.lower() or "public" in summary.lower()
    assert "Acme" not in summary
    assert '{"watchlist"' not in summary


def test_run_alone_not_acme_fixture(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    result = invoke_graph_full(g, {"messages": [HumanMessage(content="run")]})
    assert result.get("status") == "chat"
    assert not any(
        item.get("name") == "Acme" for item in watchlist_from_state(result)
    )
    summaries = " ".join(result.get("stage_summaries") or [])
    assert "gather:" not in summaries


def test_track_fedex_still_baseline_pulse(monkeypatch, tmp_path):
    """Track intent keeps first-run baseline UX — not conversational."""
    _offline(monkeypatch)
    empty_bl = tmp_path / "empty.json"
    empty_bl.write_text(json.dumps({"version": 1, "entries": []}), encoding="utf-8")

    g = compile_graph()
    result = invoke_graph_full(
        g,
        {
            "user_message": "track fedex",
            "notify": False,
            "baseline_path": str(empty_bl),
            "allow_net": False,
        },
    )
    summary = assistant_summary(result).lower()
    assert result.get("status") not in {"chat", "help", "other"}
    assert "fedex" in summary
    assert "acme" not in summary
    summaries = " ".join(result.get("stage_summaries") or [])
    assert "gather:" in summaries
    assert "analyze:" in summaries
    assert "converse:" not in summaries
