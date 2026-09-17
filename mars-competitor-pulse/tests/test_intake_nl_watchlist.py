"""Natural-language watchlist intake (offline alias map, no network)."""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage

from competitor_pulse.intake_parse import parse_watchlist_from_message
from competitor_pulse.nodes import intake
from competitor_pulse.pulse_diff import default_watchlist
from competitor_pulse.mars_text import watchlist_from_state


def _offline(monkeypatch):
    monkeypatch.delenv("HARNESS_INFERENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ALLOW_NET", "0")


def test_parse_nl_known_aliases():
    parsed = parse_watchlist_from_message(
        "Track OpenAI, Anthropic, and Google for SpaceXAI"
    )
    names = [item["name"] for item in parsed["competitors"]]
    assert names == ["OpenAI", "Anthropic", "Google AI"]
    assert parsed["source"] == "offline"
    assert parsed["notify"] is None


def test_parse_pulse_on_cursor_and_perplexity():
    parsed = parse_watchlist_from_message("Pulse on Cursor and Perplexity")
    names = [item["name"] for item in parsed["competitors"]]
    assert names == ["Cursor", "Perplexity"]
    assert parsed["is_tracking_request"] is True


def test_intake_nl_watchlist_sets_allow_net(monkeypatch):
    _offline(monkeypatch)
    result = intake(
        {
            "messages": [
                HumanMessage(
                    content="Track OpenAI, Anthropic, and Google for SpaceXAI"
                )
            ]
        }
    )
    names = {item["name"] for item in watchlist_from_state(result)}
    assert "OpenAI" in names
    assert "Anthropic" in names
    assert "Google AI" in names
    assert result["allow_net"] is True
    assert result["notify"] is False
    assert result["status"] == "ok"


def test_intake_json_still_works(monkeypatch):
    _offline(monkeypatch)
    custom = [{"name": "RivalCo", "urls": {"site": "https://example.com/rival/"}}]
    payload = {"watchlist": custom, "notify": False, "allow_net": False}
    result = intake(
        {
            "messages": [
                HumanMessage(
                    content=f"```json\n{json.dumps(payload)}\n```"
                )
            ]
        }
    )
    assert watchlist_from_state(result) == custom
    assert result["allow_net"] is False


def test_intake_generic_message_routes_to_chat(monkeypatch):
    _offline(monkeypatch)
    result = intake({"messages": [HumanMessage(content="hi")]})
    assert result.get("intent") == "chat"
    assert "watchlist" not in result
    assert "competitors" not in result
    assert "internal" not in result
    assert result["status"] == "chat"


def test_intake_no_message_uses_acme_default(monkeypatch):
    _offline(monkeypatch)
    result = intake({})
    assert watchlist_from_state(result) == default_watchlist()


def test_intake_unresolved_track_request_blocked(monkeypatch):
    _offline(monkeypatch)
    result = intake(
        {
            "messages": [
                HumanMessage(content="Track FooBar and BazQuux competitors please")
            ]
        }
    )
    assert result["status"] == "blocked"
    assert "watchlist" not in result
    assert "competitors" not in result
    assert "internal" not in result
    assert "resolve" in (result.get("blocked_reason") or "").lower()
    names = {item["name"] for item in default_watchlist()}
    assert "Acme" not in names or "Acme" not in {
        item["name"] for item in watchlist_from_state(result)
    }


def test_intake_notify_from_nl(monkeypatch):
    _offline(monkeypatch)
    result = intake(
        {
            "messages": [
                HumanMessage(content="Track Cursor and alert on Slack when changes happen")
            ]
        }
    )
    assert result["notify"] is True
    assert any(item["name"] == "Cursor" for item in watchlist_from_state(result))


def test_parse_hi_never_calls_llm_watchlist(monkeypatch):
    """Regression: generic hi must not invoke watchlist LLM (MARS JSON leak)."""
    called = {"n": 0}

    def boom(text):
        called["n"] += 1
        raise AssertionError("llm watchlist must not run for hi")

    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("COMPETITOR_PULSE_LLM_PARSE", "1")
    monkeypatch.setattr(
        "competitor_pulse.intake_parse._llm_watchlist",
        boom,
    )
    from competitor_pulse.intake_parse import parse_watchlist_from_message

    result = parse_watchlist_from_message("hi")
    assert result["is_generic"] is True
    assert result["competitors"] == []
    assert result["source"] == "none"
    assert called["n"] == 0


def test_parse_track_fedex_offline_without_llm(monkeypatch):
    """Unknown single company → empty here; intake uses parse_track_message."""
    monkeypatch.delenv("COMPETITOR_PULSE_LLM_PARSE", raising=False)
    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_INFERENCE_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("HARNESS_INFERENCE_MODEL", "dummy")

    def boom(*_a, **_k):
        raise AssertionError("llm watchlist must stay off by default")

    monkeypatch.setattr("competitor_pulse.llm.get_llm", boom)
    from competitor_pulse.intake_parse import parse_watchlist_from_message

    result = parse_watchlist_from_message("track fedex")
    assert result["is_tracking_request"] is True
    assert result["competitors"] == []
    assert result["source"] == "none"
