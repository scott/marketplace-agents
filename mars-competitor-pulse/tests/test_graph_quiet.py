"""Empty/quiet no interrupt; material gate; notify=false skips ask."""

from __future__ import annotations

import os

from competitor_pulse.graph import compile_graph
from pulse_helpers import assistant_summary, default_pulse_payload, invoke_graph, invoke_graph_full
from competitor_pulse.pulse_diff import (
    default_baseline_path,
    default_watchlist,
    material_baseline_path,
    quiet_baseline_path,
)


def _offline(monkeypatch):
    monkeypatch.delenv("HARNESS_INFERENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ALLOW_NET", "0")


def test_quiet_baseline_no_interrupt(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    result = invoke_graph_full(
        g,
        default_pulse_payload(
            notify=True,
            baseline_path=str(quiet_baseline_path()),
        ),
    )
    assert "__interrupt__" not in result
    assert result.get("status") == "empty"
    assert result.get("material") is False
    assert not result.get("deltas")
    summary = assistant_summary(result).lower()
    assert "no changes" in summary or "no material" in summary or "nothing material" in summary
    summaries = result.get("stage_summaries") or []
    assert any("analyze" in s for s in summaries)
    assert any("report" in s for s in summaries)
    assert not any(s.startswith("ask:") for s in summaries)


def test_force_empty_no_interrupt(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    result = invoke_graph(
        g,
        default_pulse_payload(
            notify=True,
            baseline_path=str(material_baseline_path()),
            force_empty=True,
        ),
    )
    assert "__interrupt__" not in result
    assert result.get("status") == "empty"
    assert result.get("material") is False


def test_material_without_notify_skips_ask(monkeypatch):
    """Material deltas but notify=false → brief, no interrupt."""
    _offline(monkeypatch)
    g = compile_graph()
    result = invoke_graph_full(
        g,
        default_pulse_payload(baseline_path=str(material_baseline_path())),
    )
    assert "__interrupt__" not in result
    assert result.get("material") is True
    assert (result.get("delta_count") or 0) >= 1
    assert result.get("brief_md")
    assert result.get("status") in {"ok", "empty"} or result.get("brief_md")
    summaries = " ".join(result.get("stage_summaries") or [])
    assert "ask:" not in summaries


def test_material_gate_requires_both(monkeypatch):
    """Ask only when notify AND material — quiet+notify still no ask."""
    _offline(monkeypatch)
    g = compile_graph()
    quiet = invoke_graph(
        g,
        {
            "notify": True,
            "baseline_path": str(quiet_baseline_path()),
            "allow_net": False,
        },
    )
    assert "__interrupt__" not in quiet
    assert quiet.get("material") is False

    from langgraph.checkpoint.memory import MemorySaver

    g2 = compile_graph(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "material-gate"}}
    mid = invoke_graph(
        g2,
        {
            "notify": True,
            "baseline_path": str(default_baseline_path()),
            "allow_net": False,
        },
        cfg,
    )
    assert "__interrupt__" in mid
    snap = g2.get_state(cfg).values
    assert snap.get("material") is True
    assert (snap.get("delta_count") or 0) >= 1


def test_blocked_no_interrupt(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    result = g.invoke({"force_blocked": True, "notify": True})
    assert "__interrupt__" not in result
    assert result.get("status") == "blocked"
