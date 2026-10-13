"""Leak-safe inference (playbook §5.8): direct HTTP ``/chat/completions`` with ``stream: false``.

Prefers HARNESS_INFERENCE_* env vars; falls back to OPENAI_*. Never uses
``llm.invoke`` so token streams cannot leak into MARS chat text.
"""

from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
PUBLIC_DO_BASE_URL = "https://inference.do-ai.run/v1"

# Safe diagnostics: last fallback reason (exception class / HTTP status only; never secrets).
LAST_ERROR: dict[str, str] = {"reason": ""}


def _fail(reason: str) -> None:
    LAST_ERROR["reason"] = reason[:160]


def last_error() -> str:
    return LAST_ERROR["reason"]


def resolve_llm_env() -> dict[str, str | None]:
    base_url = os.environ.get("HARNESS_INFERENCE_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("HARNESS_INFERENCE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    model = (
        os.environ.get("HARNESS_INFERENCE_MODEL")
        or os.environ.get("OPENAI_MODEL")
        or DEFAULT_MODEL
    )
    # Secrets passed with ``doctl --secret NAME=@file`` keep the file's trailing
    # newline; an unstripped key makes an invalid Authorization header.
    strip = lambda v: v.strip() if isinstance(v, str) else v  # noqa: E731
    return {"base_url": strip(base_url), "api_key": strip(api_key), "model": strip(model)}


def harness_env_available() -> bool:
    if os.environ.get("BOX_SUMMARIZER_LLM", "1").strip() == "0":
        return False
    return bool(resolve_llm_env()["api_key"])


def chat_completion(
    system: str,
    user: str,
    *,
    max_tokens: int = 2000,
    temperature: float = 0.2,
    timeout: float = 90.0,
) -> str | None:
    """Return assistant text or None on any failure (callers fall back to heuristics)."""
    if not harness_env_available():
        _fail("no API key (or BOX_SUMMARIZER_LLM=0)")
        return None
    msg = _post(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens, temperature=temperature, timeout=timeout,
    )
    content = ((msg or {}).get("content") or "").strip()
    if msg is not None and not content:
        _fail("empty content")
        return None
    return content or None


def chat_with_tools(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    max_tokens: int = 800,
    temperature: float = 0.3,
    timeout: float = 60.0,
) -> dict[str, Any] | None:
    """OpenAI-compatible tool calling. Returns the assistant message dict
    (``content`` and/or ``tool_calls``) or None when the LLM is unavailable."""
    if not harness_env_available():
        _fail("no API key (or BOX_SUMMARIZER_LLM=0)")
        return None
    return _post(messages, tools=tools, max_tokens=max_tokens, temperature=temperature, timeout=timeout)


def _post(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int,
    temperature: float,
    timeout: float,
) -> dict[str, Any] | None:
    import requests

    env = resolve_llm_env()
    url = (env["base_url"] or DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": env["model"],
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    headers = {"Authorization": f"Bearer {env['api_key']}", "Content-Type": "application/json"}
    body = json.dumps(payload)
    urls = [url]
    # On MARS the harness may rewrite HARNESS_INFERENCE_BASE_URL to an internal
    # trusted endpoint that rejects a tenant key (seen: HTTP 401). Retry once on
    # the public endpoint, which accepts the same key.
    public = os.environ.get("INFERENCE_PUBLIC_BASE_URL", PUBLIC_DO_BASE_URL).rstrip("/") + "/chat/completions"
    if public != url:
        urls.append(public)
    reasons: list[str] = []
    for target in urls:
        try:
            resp = requests.post(target, headers=headers, data=body, timeout=timeout)
            host = target.split("//")[-1].split("/")[0]
            if resp.status_code >= 400:
                reasons.append(f"HTTP {resp.status_code} from {host}")
                if resp.status_code in (401, 403, 404):
                    continue
                break
            choice = resp.json()["choices"][0]
            msg = dict(choice.get("message") or {})
            if not (msg.get("content") or "").strip() and not msg.get("tool_calls"):
                reasons.append(f"empty content (finish_reason={choice.get('finish_reason')})")
                break
            LAST_ERROR["reason"] = ""
            return msg
        except Exception as exc:  # noqa: BLE001 — offline fallback is the contract
            reasons.append(type(exc).__name__)
            break
    _fail("; ".join(reasons) or "unknown")
    return None


def parse_json_object(text: str | None) -> dict[str, Any] | None:
    """Best-effort JSON object extraction from a model reply."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
