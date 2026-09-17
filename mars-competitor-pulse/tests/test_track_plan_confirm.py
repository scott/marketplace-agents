"""Ghost Writer-style track plan → confirm → pulse gate."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage

from competitor_pulse.graph import compile_graph
from competitor_pulse.intent import classify_intent, is_track_confirm
from competitor_pulse.nodes import intake
from competitor_pulse.mars_text import watchlist_from_state

from pulse_helpers import assistant_summary, invoke_graph_full


def _offline(monkeypatch):
    monkeypatch.delenv("HARNESS_INFERENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ALLOW_NET", "0")


def test_classify_nl_track_is_track_plan_not_pulse():
    assert classify_intent("track fedex") == "track_plan"
    assert classify_intent("Lets add a track for Tesla too") == "track_plan"


def test_confirm_with_pending_is_pulse():
    pending = {"competitors": [{"name": "Tesla", "urls": {}}]}
    assert classify_intent("yes", pending_track=pending) == "pulse"
    assert classify_intent("go ahead", pending_track=pending) == "pulse"
    assert classify_intent("track it", pending_track=pending) == "pulse"
    assert is_track_confirm("yes")
    assert is_track_confirm("track it")


def test_combined_confirm_phrases():
    """Combined acks like 'yes, track it' must confirm (MARS smoke regression)."""
    pending = {"competitors": [{"name": "Tesla", "urls": {}}]}
    for phrase in (
        "yes, track it",
        "yes track it",
        "yes — track it",
        "ok, do it",
        "yep, go ahead",
        "sure, proceed",
        "sounds good!",
        "let's go",
        "confirmed",
    ):
        assert is_track_confirm(phrase), phrase
        assert classify_intent(phrase, pending_track=pending) == "pulse", phrase


def test_yes_track_pending_name_is_pulse():
    pending = {"competitors": [{"name": "Tesla", "urls": {}}]}
    assert is_track_confirm("Yes, track Tesla", pending_names=["Tesla"])
    assert classify_intent("Yes, track Tesla", pending_track=pending) == "pulse"
    assert classify_intent("yes track tesla", pending_track=pending) == "pulse"


def test_track_fedex_still_track_plan_not_confirm():
    """Bare 'track FedEx' is a new plan request, never a false confirm."""
    assert not is_track_confirm("track FedEx")
    assert not is_track_confirm("track FedEx", pending_names=["Tesla"])
    assert not is_track_confirm("track FedEx", pending_names=["FedEx"])
    assert classify_intent("track FedEx") == "track_plan"
    pending_tesla = {"competitors": [{"name": "Tesla", "urls": {}}]}
    # Without matching confirm words, new company request stays track_plan
    # even when something else is pending.
    assert classify_intent("track FedEx", pending_track=pending_tesla) == "track_plan"


def test_tesla_too_plan_no_immediate_baseline(monkeypatch, tmp_path):
    """Add Tesla too → plan/confirm; no gather until yes."""
    _offline(monkeypatch)
    monkeypatch.setenv("COMPETITOR_PULSE_LLM_PARSE", "0")
    fedex = [{"name": "FedEx", "urls": {"site": "https://www.fedex.com/"}}]
    result = intake(
        {
            "messages": [HumanMessage(content="Lets add a track for Tesla too")],
            "internal": {"competitors": fedex},
        }
    )
    assert result.get("intent") == "track_plan"
    assert result.get("status") == "track_plan"
    pending = result.get("pending_track") or {}
    pending_names = [item["name"] for item in pending.get("competitors") or []]
    assert "Tesla" in pending_names
    assert "FedEx" in pending_names
    msg = result["messages"][0]
    assert isinstance(msg, AIMessage)
    text = msg.content.lower()
    assert "tesla" in text
    assert "fedex" in text
    assert "track" in text
    assert "without your ok" in text or "will not notify" in text
    assert "baseline" not in text or "first pass" in text
    summaries = " ".join(result.get("stage_summaries") or [])
    assert "gather:" not in summaries


def test_yes_after_plan_runs_pulse(monkeypatch, tmp_path):
    """Confirm after plan → pulse with gather."""
    _offline(monkeypatch)
    monkeypatch.setenv("COMPETITOR_PULSE_LLM_PARSE", "0")
    empty_bl = tmp_path / "empty.json"
    empty_bl.write_text(json.dumps({"version": 1, "entries": []}), encoding="utf-8")

    pending = {
        "competitors": [
            {"name": "FedEx", "urls": {"site": "https://www.fedex.com/"}},
            {"name": "Tesla", "urls": {"site": "https://www.tesla.com/"}},
        ],
        "notify": False,
        "allow_net": False,
        "channel": "slack",
    }
    g = compile_graph()
    result = invoke_graph_full(
        g,
        {
            "messages": [HumanMessage(content="yes")],
            "pending_track": pending,
            "baseline_path": str(empty_bl),
            "allow_net": False,
        },
    )
    summary = assistant_summary(result).lower()
    assert result.get("status") not in {"chat", "help", "other", "track_plan"}
    assert "fedex" in summary or "tesla" in summary
    summaries = " ".join(result.get("stage_summaries") or [])
    assert "gather:" in summaries
    assert "analyze:" in summaries


def test_hi_still_clean_chat(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    result = invoke_graph_full(g, {"messages": [HumanMessage(content="hi")]})
    summary = assistant_summary(result)
    assert result.get("status") == "chat"
    assert "Acme" not in summary
    summaries = " ".join(result.get("stage_summaries") or [])
    assert "gather:" not in summaries
