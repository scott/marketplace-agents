from box_doc_summarizer.intent import classify_intent, parse_folder_id
from box_doc_summarizer.llm import harness_env_available, parse_json_object, resolve_llm_env


def test_folder_parsing():
    assert parse_folder_id("Summarize folder 123456789") == "123456789"
    assert parse_folder_id("https://app.box.com/folder/987654321") == "987654321"
    assert parse_folder_id("hi") == ""


def test_intents():
    assert classify_intent("hi") == "chat"
    assert classify_intent("help") == "help"
    assert classify_intent("Summarize folder 123456") == "summarize"
    assert classify_intent("refresh") == "summarize"


def test_llm_env_prefers_harness(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "h")
    monkeypatch.setenv("HARNESS_INFERENCE_MODEL", "m")
    env = resolve_llm_env()
    assert env["api_key"] == "h" and env["model"] == "m"
    assert harness_env_available()
    monkeypatch.setenv("BOX_SUMMARIZER_LLM", "0")
    assert not harness_env_available()


def test_parse_json_object():
    assert parse_json_object('```json\n{"brief": "x"}\n```') == {"brief": "x"}
    assert parse_json_object("nope") is None


def test_fallback_reason_recorded(monkeypatch):
    import requests

    from box_doc_summarizer import llm

    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "k")

    class R:
        status_code = 401

    monkeypatch.setattr(requests, "post", lambda *a, **k: R())
    assert llm.chat_completion("s", "u") is None
    assert "HTTP 401" in llm.last_error() and "Bearer" not in llm.last_error()

    def boom(*a, **k):
        raise requests.ConnectionError("x")

    monkeypatch.setattr(requests, "post", boom)
    llm.chat_completion("s", "u")
    assert llm.last_error() == "ConnectionError"


def test_key_from_file_newline_is_stripped(monkeypatch):
    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "abc\n")
    assert resolve_llm_env()["api_key"] == "abc"


def test_401_on_rewritten_endpoint_retries_public(monkeypatch):
    import requests

    from box_doc_summarizer import llm

    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "k")
    monkeypatch.setenv("HARNESS_INFERENCE_BASE_URL", "http://inference-trusted.internal/v1")
    calls = []

    class R:
        def __init__(self, code):
            self.status_code = code

        def json(self):
            return {"choices": [{"message": {"content": "hello"}}]}

    def post(url, **k):
        calls.append(url)
        return R(401 if "internal" in url else 200)

    monkeypatch.setattr(requests, "post", post)
    assert llm.chat_completion("s", "u") == "hello"
    assert calls[1].startswith("https://inference.do-ai.run/v1")
