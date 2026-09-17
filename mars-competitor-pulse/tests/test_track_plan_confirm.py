"""Ghost Writer-style track plan → confirm → pulse gate (Sol §10 / §11)."""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage, HumanMessage

from competitor_pulse.graph import compile_graph
from competitor_pulse.intent import (
    classify_intent,
    is_skip_confirm_cue,
    is_track_confirm,
    is_track_deny,
)
from competitor_pulse.nodes import intake
from competitor_pulse.persona import track_plan_message

from pulse_helpers import assistant_summary, invoke_graph_full


def _offline(monkeypatch):
    monkeypatch.delenv("HARNESS_INFERENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ALLOW_NET", "0")


def test_classify_nl_track_is_track_plan_not_pulse():
    assert classify_intent("track fedex") == "track_plan"
    assert classify_intent("Lets add a track for Tesla too") == "track_plan"


def test_skip_confirm_cue_routes_pulse():
    assert is_skip_confirm_cue("Track FedEx now")
    assert classify_intent("Track FedEx now") == "pulse"


def test_confirm_with_pending_is_pulse():
    pending = {"competitors": [{"name": "Tesla", "urls": {}}]}
    assert classify_intent("yes", pending_track=pending) == "pulse"
    assert classify_intent("go ahead", pending_track=pending) == "pulse"
    assert classify_intent("track it", pending_track=pending) == "pulse"
    assert is_track_confirm("yes")
    assert is_track_confirm("run it")


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


def test_deny_with_pending_is_chat():
    pending = {"competitors": [{"name": "Tesla", "urls": {}}]}
    assert classify_intent("no", pending_track=pending) == "chat"
    assert is_track_deny("cancel")


def test_track_plan_message_sol_shape():
    plan = track_plan_message(["FedEx"], notify=False, has_baseline=False)
    assert plan.startswith("Here's the watch plan:")
    assert "Companies: FedEx" in plan
    assert "Modules: site, pricing, changelog, careers" in plan
    assert "Notify: off (brief only)." in plan
    assert "First pass will only set baselines" in plan
    assert plan.strip().endswith("Want me to start this watch and run a pulse?")


def test_track_plan_merge_message_sol_shape():
    plan = track_plan_message(
        ["FedEx", "Tesla"],
        merge_current=["FedEx"],
        merge_added=["Tesla"],
        has_baseline=True,
    )
    assert plan.startswith("Add to the current watch?")
    assert "Already watching: FedEx" in plan
    assert "Add: Tesla" in plan
    assert "Full list would be: FedEx, Tesla" in plan
    assert "Want me to update the watch and run a pulse?" in plan


def test_tesla_too_plan_no_immediate_baseline(monkeypatch):
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
    text = msg.content
    assert "Add to the current watch?" in text
    assert "Tesla" in text
    assert "FedEx" in text
    assert "?" in text.split("\n")[0] or "?" in text
    assert "Want me to update the watch and run a pulse?" in text
    summaries = " ".join(result.get("stage_summaries") or [])
    assert "gather:" not in summaries


def test_add_tesla_too_plan_then_confirm_full_graph(monkeypatch, tmp_path):
    """Full graph: watch FedEx → add Tesla too plan → yes → pulse with gather."""
    _offline(monkeypatch)
    monkeypatch.setenv("COMPETITOR_PULSE_LLM_PARSE", "0")
    empty_bl = tmp_path / "empty.json"
    empty_bl.write_text(json.dumps({"version": 1, "entries": []}), encoding="utf-8")

    from langgraph.checkpoint.memory import MemorySaver

    g = compile_graph(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "tesla-merge-flow"}}
    base = {"baseline_path": str(empty_bl), "allow_net": False}

    plan_fedex = invoke_graph_full(
        g,
        {**base, "messages": [HumanMessage(content="track fedex")]},
        cfg,
    )
    assert plan_fedex.get("status") == "track_plan"
    pending_fedex = plan_fedex.get("pending_track")
    assert pending_fedex

    watched = invoke_graph_full(
        g,
        {
            **base,
            "messages": [HumanMessage(content="yes")],
            "pending_track": pending_fedex,
        },
        cfg,
    )
    assert watched.get("status") not in {"chat", "help", "track_plan"}

    plan = invoke_graph_full(
        g,
        {**base, "messages": [HumanMessage(content="Lets add a track for Tesla too")]},
        cfg,
    )
    assert plan.get("status") == "track_plan"
    plan_text = assistant_summary(plan)
    assert "Add to the current watch?" in plan_text
    assert "Tesla" in plan_text
    assert "FedEx" in plan_text
    assert plan.get("pending_track")

    pending = plan.get("pending_track")
    assert pending
    result = invoke_graph_full(
        g,
        {
            **base,
            "messages": [HumanMessage(content="yes")],
            "pending_track": pending,
        },
        cfg,
    )
    assert result.get("status") not in {"chat", "help", "other", "track_plan"}
    summary = assistant_summary(result).lower()
    assert "fedex" in summary or "tesla" in summary or "on it" in summary
    summaries = " ".join(result.get("stage_summaries") or [])
    assert "gather:" in summaries
    assert "analyze:" in summaries


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
    assert "fedex" in summary or "tesla" in summary or "on it" in summary
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
