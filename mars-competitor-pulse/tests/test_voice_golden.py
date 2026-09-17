"""P1 golden voice fixtures (Sol PULSE-PERSONA-COPY §9)."""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage

from competitor_pulse.converse import conversational_reply
from competitor_pulse.draft_llm import synthesize_material_draft, template_material_draft
from competitor_pulse.graph import compile_graph
from competitor_pulse.hygiene import hygiene_text
from competitor_pulse.mars_text import (
    assemble_doctl_prompt_text,
    hi_chat_payload,
    prepare_programmatic_payload,
)
from competitor_pulse.persona import (
    WELCOME_STARTERS,
    ask_body,
    quiet_message,
    welcome_message,
)
from competitor_pulse.pulse_diff import (
    default_fixture_dir,
    default_watchlist,
    material_baseline_path,
)
from pulse_helpers import assistant_summary, default_pulse_payload, invoke_graph


def _offline(monkeypatch):
    monkeypatch.delenv("HARNESS_INFERENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("COMPETITOR_PULSE_LLM_DRAFT", raising=False)
    monkeypatch.delenv("COMPETITOR_PULSE_LLM_PARSE", raising=False)
    monkeypatch.setenv("ALLOW_NET", "0")


def test_voice_hi_safety(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    result = g.invoke({"messages": [HumanMessage(content="hi")], "allow_net": False})
    summary = assistant_summary(result).lower()
    assert "without your ok" in summary or "will not notify" in summary
    assert "—" not in assistant_summary(result)
    assert " -- " not in assistant_summary(result)


def test_voice_hi_starters(monkeypatch):
    _offline(monkeypatch)
    w = welcome_message()
    for starter in WELCOME_STARTERS:
        assert starter in w
    reply = conversational_reply("chat", "hi")
    for starter in WELCOME_STARTERS:
        assert starter in reply


def test_voice_brief_no_review_enum_and_no_counter_prefix():
    deltas = [
        {
            "competitor": "Acme",
            "module": "pricing",
            "change_type": "pricing_change",
            "summary": "Pro tier seats dropped",
            "evidence_url": "https://example.com/pricing",
        },
        {
            "competitor": "Globex",
            "module": "site",
            "change_type": "site_copy_change",
            "summary": "Homepage headline shifted",
            "evidence_url": "https://example.com/",
        },
    ]
    out = template_material_draft(deltas)
    brief = out["brief_md"]
    assert "review site_copy_change" not in brief
    assert "review pricing_change" not in brief
    assert "Counter " not in brief
    for c in out["counterpositions"]:
        assert not c.startswith("Counter ")
        assert "review site_copy_change" not in c


def test_voice_quiet_line():
    q = quiet_message(["Acme"])
    assert "Nothing material moved since your last baseline. Staying quiet." in q
    assert "Status: empty" not in q
    assert "status:" not in q.lower()


def test_voice_ask_question_first():
    body = ask_body(
        channel="slack",
        delta_count=1,
        names=["Acme"],
        highlights="- Acme: pricing moved",
        notify_draft="Pulse: 1 material change(s) on Acme.",
    )
    first = next(line for line in body.splitlines() if line.strip())
    assert "?" in first
    assert "slack" in first.lower()


def test_voice_hygiene_emdash():
    dirty = (
        "Hello — world -- and more.\n"
        "intake: done\n"
        "status: ok\n"
        "Certainly, I can help.\n"
        '```json\n{"watchlist":[]}\n```\n'
        "- Counter Acme/pricing: review pricing_change — seats dropped"
    )
    clean = hygiene_text(dirty)
    assert "—" not in clean
    assert " -- " not in clean
    assert "intake:" not in clean.lower()
    assert "status: ok" not in clean.lower()
    assert "Certainly," not in clean
    assert "watchlist" not in clean
    assert "review pricing_change" not in clean
    assert "Counter Acme" not in clean


def test_voice_help_topic_modules(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    result = g.invoke(
        {"messages": [HumanMessage(content="what modules do you watch?")], "allow_net": False}
    )
    summary = assistant_summary(result).lower()
    assert result.get("status") == "help"
    assert "pricing" in summary and "careers" in summary
    assert "changelog" in summary


def test_voice_mars_assemble_no_competitors_json(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    raw = assemble_doctl_prompt_text(g, hi_chat_payload())
    assert '{"competitors"' not in raw
    assert '{"watchlist"' not in raw
    assert raw.count("Baseline set") == 0  # hi path, not track


def test_voice_baseline_set_once_first_look(monkeypatch, tmp_path):
    _offline(monkeypatch)
    empty_bl = tmp_path / "empty.json"
    empty_bl.write_text(json.dumps({"version": 1, "entries": []}), encoding="utf-8")
    g = compile_graph()
    fixture_dir = default_fixture_dir()
    payload = prepare_programmatic_payload(
        {
            "competitors": default_watchlist(),
            "allow_net": False,
            "notify": False,
            "baseline_path": str(empty_bl),
            "fixture_dir": str(fixture_dir),
            "snapshot_dir": str(fixture_dir / "snapshots"),
        }
    )
    raw = assemble_doctl_prompt_text(g, payload)
    assert raw.count("Baseline set") == 1


def test_voice_material_graph_brief_clean(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    result = invoke_graph(
        g,
        default_pulse_payload(baseline_path=str(material_baseline_path())),
    )
    brief = result.get("brief_md") or ""
    assert "review site_copy_change" not in brief
    assert "Counter " not in brief
    assert "—" not in brief
    assert result.get("material") is True


def test_synthesize_defaults_to_template_without_flag(monkeypatch):
    _offline(monkeypatch)
    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "should-not-call")
    monkeypatch.setenv("HARNESS_INFERENCE_BASE_URL", "https://example.invalid/v1")

    def boom(*_a, **_k):
        raise AssertionError("LLM draft must stay off by default")

    monkeypatch.setattr("competitor_pulse.llm.get_llm", boom)
    out = synthesize_material_draft(
        [
            {
                "competitor": "Acme",
                "module": "pricing",
                "summary": "price drop",
                "evidence_url": "https://example.com/p",
            }
        ]
    )
    assert out["draft_source"] == "template"
    assert "Counter " not in out["brief_md"]
