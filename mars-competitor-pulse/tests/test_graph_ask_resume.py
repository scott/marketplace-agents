"""Ask payload Sol contract; resume approve/deny."""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from competitor_pulse.graph import compile_graph
from pulse_helpers import default_pulse_payload, invoke_graph
from competitor_pulse.pulse_diff import default_baseline_path


def _offline(monkeypatch):
    monkeypatch.delenv("HARNESS_INFERENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ALLOW_NET", "0")


def _run_to_interrupt(monkeypatch, thread_id: str = "pulse-ask"):
    _offline(monkeypatch)
    g = compile_graph(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": thread_id}}
    result = invoke_graph(
        g,
        default_pulse_payload(
            notify=True,
            channel="slack",
            baseline_path=str(default_baseline_path()),
        ),
        cfg,
    )
    return g, cfg, result


def test_ask_payload_contract(monkeypatch):
    _g, _cfg, result = _run_to_interrupt(monkeypatch, "ask-contract")
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload.get("title") == "Want me to send this pulse notify via slack?"
    assert payload.get("pending_action") == "notify"
    assert payload.get("choices") == ["approve", "deny"]
    body = payload.get("body") or ""
    assert "Want me to send this pulse notify via" in body
    assert "material change" in body.lower()
    assert "Highlights:" in body
    assert "Notify draft:" in body
    assert "I will not:" in body
    assert "v1 note:" in body.lower() or "stub" in body.lower()
    assert "approve" in payload.get("choices", [])
    assert "deny" in payload.get("choices", [])


def test_resume_deny_no_notify(monkeypatch):
    g, cfg, result = _run_to_interrupt(monkeypatch, "deny-path")
    assert "__interrupt__" in result

    final = g.invoke(Command(resume="deny"), cfg)
    assert "__interrupt__" not in final
    assert final.get("status") == "denied"
    assert final.get("skipped") is True
    assert final.get("notified") is not True
    assert not final.get("notify_id")
    assert final.get("decision") == "deny"
    assert final.get("brief_md")  # brief kept


def test_resume_approve_stub_notify(monkeypatch):
    g, cfg, result = _run_to_interrupt(monkeypatch, "approve-path")
    assert "__interrupt__" in result

    final = g.invoke(Command(resume="approve"), cfg)
    assert "__interrupt__" not in final
    assert final.get("status") == "notified"
    assert final.get("skipped") is not True
    assert final.get("notified") is True
    assert final.get("decision") == "approve"
    assert (final.get("notify_id") or "").startswith("stub-notify-")
    assert final.get("brief_md")
