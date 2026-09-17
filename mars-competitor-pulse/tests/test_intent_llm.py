"""Intent LLM: direct HTTP classify + reply; no LangChain invoke."""

from __future__ import annotations

import json
from competitor_pulse.intent import classify_intent, is_chat_message
from competitor_pulse import intent_llm
from competitor_pulse.converse import conversational_reply
from competitor_pulse.persona import welcome_message


def _mock_http_content(monkeypatch, content: str):
    """Stub urllib so chat_completions returns ``content`` without network."""

    class _Resp:
        def read(self):
            payload = {
                "choices": [{"message": {"content": content}}],
            }
            return json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(_req, timeout=None):
        return _Resp()

    monkeypatch.setattr(intent_llm.urllib.request, "urlopen", fake_urlopen)


def test_hey_yo_hello_chat_offline_via_regex():
    for msg in ("hey", "yo", "hello", "hi", "what's good"):
        assert is_chat_message(msg) is True
        assert classify_intent(msg) == "chat"


def test_state_competitors_plus_hey_still_chat():
    wl = [{"name": "FedEx", "urls": {"site": "https://www.fedex.com/"}}]
    assert classify_intent("hey", state_watchlist=wl) == "chat"
    assert classify_intent("yo", state_watchlist=wl) == "chat"
    assert classify_intent("what do you do?", state_watchlist=wl) == "help"


def test_track_fedex_still_pulse_with_state():
    wl = [{"name": "Acme", "urls": {}}]
    assert classify_intent("track fedex", state_watchlist=wl) == "pulse"
    assert classify_intent("can you watch Shopify for me") == "pulse"


def test_empty_still_pulse_programmatic():
    assert classify_intent("") == "pulse"
    assert classify_intent("", state_watchlist=[{"name": "X"}]) == "pulse"


def test_ambiguous_phrase_mocked_http_classifies_chat(monkeypatch):
    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_INFERENCE_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("HARNESS_INFERENCE_MODEL", "dummy")
    _mock_http_content(monkeypatch, "chat")
    assert classify_intent("how's your day") == "chat"
    assert classify_intent("tell me a joke") == "chat"


def test_austin_self_driving_reply_suggests_tesla(monkeypatch):
    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_INFERENCE_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("HARNESS_INFERENCE_MODEL", "dummy")
    reply = (
        "Sounds like Tesla — Austin HQ, building self-driving / Full Self-Driving. "
        "Want me to Track Tesla?"
    )
    _mock_http_content(monkeypatch, reply)
    # Ambiguous describe-a-company → other (or chat) offline would be other;
    # with LLM classify returning chat first call — we only mock one response.
    # Drive reply path directly + classify with forced intent via converse.
    out = conversational_reply(
        "other",
        "I am thinking of a tech company based in Austin that builds a self driving car",
    )
    assert "Tesla" in out
    assert "track" in out.lower()
    assert '{"watchlist"' not in out
    assert '{"competitors"' not in out


def test_classify_path_never_calls_get_llm(monkeypatch):
    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_INFERENCE_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("HARNESS_INFERENCE_MODEL", "dummy")
    _mock_http_content(monkeypatch, "chat")

    def boom(*_a, **_k):
        raise AssertionError("classify must not call get_llm")

    monkeypatch.setattr("competitor_pulse.llm.get_llm", boom)
    assert classify_intent("how's your day") == "chat"


def test_conversational_reply_never_calls_get_llm(monkeypatch):
    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_INFERENCE_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("HARNESS_INFERENCE_MODEL", "dummy")
    _mock_http_content(monkeypatch, "Brief hello. Track OpenAI?")

    def boom(*_a, **_k):
        raise AssertionError("converse must not call get_llm")

    monkeypatch.setattr("competitor_pulse.llm.get_llm", boom)
    # Freeform (not bare greeting) → LLM HTTP path
    out = conversational_reply("chat", "how's your day going?")
    assert "Track" in out or "track" in out.lower() or "hello" in out.lower()


def test_offline_hey_uses_welcome_template():
    assert conversational_reply("chat", "hey") == welcome_message()
    assert conversational_reply("chat", "yo") == welcome_message()


def test_chat_completions_stream_false_in_body(monkeypatch):
    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_INFERENCE_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("HARNESS_INFERENCE_MODEL", "dummy")
    seen = {}

    class _Resp:
        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "chat"}}]}
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, timeout=None):
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(intent_llm.urllib.request, "urlopen", fake_urlopen)
    assert intent_llm.classify_intent_llm("how's your day") == "chat"
    assert seen["body"]["stream"] is False
    assert seen["url"].endswith("/chat/completions")
