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


def test_intake_nl_watchlist_plan_not_immediate_pulse(monkeypatch):
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
    assert result.get("intent") == "track_plan"
    assert result.get("status") == "track_plan"
    assert watchlist_from_state(result) == []
    text = result["messages"][0].content.lower()
    assert "openai" in text
    assert "anthropic" in text
    assert "watch plan" in text or "start this watch" in text


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


def test_intake_notify_from_nl_in_plan(monkeypatch):
    _offline(monkeypatch)
    result = intake(
        {
            "messages": [
                HumanMessage(content="Track Cursor and alert on Slack when changes happen")
            ]
        }
    )
    assert result.get("intent") == "track_plan"
    text = result["messages"][0].content.lower()
    assert "cursor" in text
    assert "slack" in text or "notify" in text
    pending = result.get("pending_track") or {}
    assert pending.get("notify") is True


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
    """FedEx is a known alias → offline; kill-switch keeps LLM dark."""
    monkeypatch.setenv("COMPETITOR_PULSE_LLM_PARSE", "0")
    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_INFERENCE_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("HARNESS_INFERENCE_MODEL", "dummy")

    def boom(*_a, **_k):
        raise AssertionError("llm watchlist must not run when PARSE=0")

    monkeypatch.setattr("competitor_pulse.llm.get_llm", boom)
    monkeypatch.setattr(
        "competitor_pulse.intent_llm.chat_completions",
        boom,
    )
    from competitor_pulse.intake_parse import parse_watchlist_from_message

    result = parse_watchlist_from_message("track fedex")
    assert result["is_tracking_request"] is True
    assert [c["name"] for c in result["competitors"]] == ["FedEx"]
    assert result["source"] == "offline"


def test_parse_add_track_for_tesla_too_offline_alias(monkeypatch):
    """Scott's live bug phrase → Tesla via alias, never 'A Track For Tesla Too'."""
    monkeypatch.setenv("COMPETITOR_PULSE_LLM_PARSE", "0")
    monkeypatch.delenv("HARNESS_INFERENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from competitor_pulse.intake_parse import parse_watchlist_from_message
    from competitor_pulse.chat import parse_track_message

    result = parse_watchlist_from_message("Lets add a track for Tesla too")
    names = [c["name"] for c in result["competitors"]]
    assert names == ["Tesla"]
    assert result["source"] == "offline"
    assert result["is_merge"] is True
    # Dumb regex must not invent a garbage company name for this phrase.
    assert parse_track_message("Lets add a track for Tesla too") is None


def test_llm_watchlist_uses_chat_completions_stream_false(monkeypatch):
    """LLM parse uses intent_llm.chat_completions (stream:false), never get_llm."""
    import json
    from competitor_pulse import intent_llm
    from competitor_pulse import intake_parse

    monkeypatch.delenv("COMPETITOR_PULSE_LLM_PARSE", raising=False)  # ON by default
    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_INFERENCE_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("HARNESS_INFERENCE_MODEL", "dummy")

    seen = {}

    class _Resp:
        def read(self):
            payload = {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "competitors": [
                                        {
                                            "name": "Shopify",
                                            "urls": {
                                                "site": "https://www.shopify.com/"
                                            },
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=None):
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["url"] = req.full_url
        return _Resp()

    def boom(*_a, **_k):
        raise AssertionError("watchlist LLM must not call get_llm")

    monkeypatch.setattr(intent_llm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("competitor_pulse.llm.get_llm", boom)

    # Unknown company + no alias → LLM path
    result = intake_parse.parse_watchlist_from_message(
        "please watch Shopify and keep me posted"
    )
    assert [c["name"] for c in result["competitors"]] == ["Shopify"]
    assert result["source"] == "llm"
    assert seen["body"]["stream"] is False
    assert seen["url"].endswith("/chat/completions")


def test_intake_merge_fedex_plus_tesla_too_plan(monkeypatch):
    """Existing FedEx + 'add Tesla too' → plan with merged names; no immediate pulse."""
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
    text = result["messages"][0].content
    assert "Add to the current watch?" in text
    pending = result.get("pending_track") or {}
    pending_names = [item["name"] for item in pending.get("competitors") or []]
    assert "Tesla" in pending_names
    assert "FedEx" in pending_names


def test_parse_track_message_simple_fedex_still_works():
    from competitor_pulse.chat import parse_track_message

    out = parse_track_message("track fedex")
    assert out is not None
    assert out[0]["name"] == "Fedex" or out[0]["name"].lower() == "fedex"
