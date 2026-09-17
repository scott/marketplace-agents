"""doctl agent prompt ``text`` shape: no watchlist JSON, greeting once."""

from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage

from competitor_pulse.chat import contains_watchlist_json
from competitor_pulse.graph import compile_graph
from competitor_pulse.mars_text import (
    assemble_doctl_prompt_text,
    hi_chat_payload,
    strip_doctl_artifacts,
)

_GREETING_RE = re.compile(
    r"(?:Hey there|Hey — I'm|Hey, welcome).{0,40}Competitor Pulse|"
    r"I'm Competitor Pulse",
    re.IGNORECASE,
)


def _offline(monkeypatch):
    monkeypatch.delenv("HARNESS_INFERENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ALLOW_NET", "0")


def _greeting_count(text: str) -> int:
    return len(_GREETING_RE.findall(text))


def test_doctl_text_hi_without_watchlist_input(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    payload = hi_chat_payload()
    raw = assemble_doctl_prompt_text(g, payload)
    # Raw must already be clean — strip_doctl_artifacts is last-resort only.
    assert not contains_watchlist_json(raw)
    assert '{"competitors"' not in raw
    assert '{"watchlist"' not in raw
    assert _greeting_count(raw) == 1
    assert "Competitor Pulse" in raw
    text = strip_doctl_artifacts(raw)
    assert _greeting_count(text) == 1


def test_doctl_text_hi_rejects_legacy_empty_list_input(monkeypatch):
    """Input schema must not expose list fields; legacy [] cannot prefix ``text``."""
    _offline(monkeypatch)
    g = compile_graph()
    payload = hi_chat_payload(include_empty_watchlist=True)
    raw = assemble_doctl_prompt_text(g, payload)
    text = strip_doctl_artifacts(raw)
    assert not contains_watchlist_json(text)
    assert _greeting_count(text) == 1


def test_doctl_text_track_fedex_first_run_clean(monkeypatch, tmp_path):
    """NL track path: no JSON leaks; ack once (offline FedEx has no fixtures → quiet OK)."""
    _offline(monkeypatch)
    empty_bl = tmp_path / "empty.json"
    empty_bl.write_text(json.dumps({"version": 1, "entries": []}), encoding="utf-8")
    g = compile_graph()
    payload = {
        "messages": [HumanMessage(content="track fedex")],
        "allow_net": False,
        "baseline_path": str(empty_bl),
    }
    raw = assemble_doctl_prompt_text(g, payload)
    assert not contains_watchlist_json(raw)
    assert '{"competitors"' not in raw
    assert raw.count("Got it") == 1
    text = strip_doctl_artifacts(raw)
    assert text.lower().count("fedex") >= 1


def test_doctl_text_first_run_baseline_body_once(monkeypatch, tmp_path):
    """First-look assemble: Baseline set appears once (not summary+brief_md across ---)."""
    _offline(monkeypatch)
    from competitor_pulse.mars_text import prepare_programmatic_payload
    from competitor_pulse.pulse_diff import (
        default_fixture_dir,
        default_watchlist,
    )

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
    assert not contains_watchlist_json(raw)
    assert raw.count("Baseline set") == 1
    assert raw.count("No notify on a first look") == 1
    assert raw.count("I saved public snapshots") == 1
    assert "\n\n---\n\nBaseline set" not in raw


def test_track_first_run_aimessage_has_single_baseline_body(monkeypatch, tmp_path):
    """Report AIMessage: ack + one baseline section + captures; no duplicated brief."""
    _offline(monkeypatch)
    from langchain_core.messages import AIMessage

    from competitor_pulse.mars_text import prepare_programmatic_payload
    from competitor_pulse.pulse_diff import default_fixture_dir, default_watchlist

    empty_bl = tmp_path / "empty.json"
    empty_bl.write_text(json.dumps({"version": 1, "entries": []}), encoding="utf-8")
    g = compile_graph()
    fixture_dir = default_fixture_dir()
    result = g.invoke(
        prepare_programmatic_payload(
            {
                "competitors": default_watchlist(),
                "allow_net": False,
                "notify": False,
                "baseline_path": str(empty_bl),
                "fixture_dir": str(fixture_dir),
                "snapshot_dir": str(fixture_dir / "snapshots"),
            }
        )
    )
    assert result.get("first_run") is True
    assert result.get("status") == "baseline"
    ai = next(m for m in reversed(result.get("messages") or []) if isinstance(m, AIMessage))
    content = ai.content if isinstance(ai.content, str) else str(ai.content)
    assert content.count("Baseline set") == 1
    assert content.count("I saved public snapshots") == 1
    assert result.get("brief_md")
    assert result["brief_md"] in content
    assert "\n\n---\n\n" not in content


def test_doctl_text_hi_stream_updates_never_emit_human_summary(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    payload = hi_chat_payload()
    for chunk in g.stream(payload, stream_mode="updates"):
        for node, update in chunk.items():
            u = update or {}
            assert "human_summary" not in u
            assert "watchlist" not in u
            assert "competitors" not in u
            assert "internal" not in u
            assert "converse_reply" not in u
            assert "chat_ack" not in u
            if node == "intake" and "messages" in u:
                # Chat path: intake emits AIMessage and ends (no converse node).
                assert "intent" in u
                assert "messages" in u
                # Scalars OK; never empty list fields or competitor payloads.
                assert "deltas" not in u
                assert "watchlist" not in u
                assert "competitors" not in u
                assert "internal" not in u
                assert set(u.keys()) <= {
                    "messages",
                    "intent",
                    "status",
                    "material",
                    "skipped",
                    "notified",
                }


def test_track_stream_updates_omit_competitors_and_chat_ack(monkeypatch, tmp_path):
    _offline(monkeypatch)
    empty_bl = tmp_path / "empty.json"
    empty_bl.write_text(json.dumps({"version": 1, "entries": []}), encoding="utf-8")
    g = compile_graph()
    payload = {
        "messages": [HumanMessage(content="track fedex")],
        "allow_net": False,
        "baseline_path": str(empty_bl),
    }
    for chunk in g.stream(payload, stream_mode="updates"):
        for _node, update in chunk.items():
            u = update or {}
            assert "competitors" not in u
            assert "watchlist" not in u
            assert "internal" not in u
            assert "chat_ack" not in u


def test_input_schema_excludes_watchlist(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    schema = g.get_input_jsonschema()
    props = schema.get("properties") or {}
    assert "watchlist" not in props
    assert "competitors" not in props
    assert "internal" not in props
    assert "messages" in props


def test_output_schema_messages_only_for_chat_text(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    schema = g.get_output_jsonschema()
    props = schema.get("properties") or {}
    assert "messages" in props
    assert "human_summary" not in props
    assert "watchlist" not in props
    assert "competitors" not in props
    assert "internal" not in props


def test_schemas_printable_proof_no_watchlist(monkeypatch, capsys):
    """Regression guard: exported JSON schemas must not expose ``watchlist``."""
    _offline(monkeypatch)
    g = compile_graph()
    for getter in (g.get_input_jsonschema, g.get_output_jsonschema):
        print(json.dumps(getter(), indent=2, sort_keys=True))
    captured = capsys.readouterr().out
    assert '"watchlist"' not in captured
    assert '"internal"' not in captured


def test_strip_doctl_artifacts_removes_empty_list_prefix():
    prefix = '{"watchlist":[]}'
    body = "Hey — I'm **Competitor Pulse**"
    assert strip_doctl_artifacts(prefix + body) == body


def test_strip_doctl_artifacts_dedupes_greeting(monkeypatch):
    _offline(monkeypatch)
    g = compile_graph()
    raw = assemble_doctl_prompt_text(g, hi_chat_payload())
    if _greeting_count(raw) >= 2:
        cleaned = strip_doctl_artifacts(raw)
        assert _greeting_count(cleaned) == 1
