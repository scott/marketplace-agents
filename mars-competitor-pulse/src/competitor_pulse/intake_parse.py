"""Natural-language watchlist parsing for MARS chat intake."""

from __future__ import annotations

import json
import re
from typing import Any

# Canonical company entries keyed by primary display name.
_KNOWN_COMPANIES: dict[str, dict[str, Any]] = {
    "OpenAI": {
        "name": "OpenAI",
        "urls": {
            "site": "https://openai.com/",
            "pricing": "https://openai.com/api/pricing/",
            "changelog": "https://openai.com/blog/",
            "careers": "https://openai.com/careers/",
        },
    },
    "Anthropic": {
        "name": "Anthropic",
        "urls": {
            "site": "https://www.anthropic.com/",
            "pricing": "https://www.anthropic.com/pricing",
            "changelog": "https://www.anthropic.com/news",
            "careers": "https://www.anthropic.com/careers",
        },
    },
    "Google AI": {
        "name": "Google AI",
        "urls": {
            "site": "https://ai.google/",
            "pricing": "https://ai.google/pricing/",
        },
    },
    "Google DeepMind": {
        "name": "Google DeepMind",
        "urls": {
            "site": "https://deepmind.google/",
            "changelog": "https://deepmind.google/discover/blog/",
        },
    },
    "Perplexity": {
        "name": "Perplexity",
        "urls": {
            "site": "https://www.perplexity.ai/",
            "pricing": "https://www.perplexity.ai/pro",
        },
    },
    "Microsoft Copilot": {
        "name": "Microsoft Copilot",
        "urls": {
            "site": "https://www.microsoft.com/en-us/microsoft-copilot",
            "pricing": "https://www.microsoft.com/en-us/microsoft-365/business/compare-all-microsoft-365-business-products",
        },
    },
    "xAI": {
        "name": "xAI",
        "urls": {
            "site": "https://x.ai/",
            "changelog": "https://x.ai/news",
        },
    },
    "Cursor": {
        "name": "Cursor",
        "urls": {
            "site": "https://cursor.com/",
            "pricing": "https://cursor.com/pricing",
            "changelog": "https://cursor.com/changelog",
        },
    },
    "Meta AI": {
        "name": "Meta AI",
        "urls": {
            "site": "https://ai.meta.com/",
            "changelog": "https://ai.meta.com/blog/",
        },
    },
    "Mistral": {
        "name": "Mistral",
        "urls": {
            "site": "https://mistral.ai/",
            "pricing": "https://mistral.ai/pricing",
            "changelog": "https://mistral.ai/news",
        },
    },
    "Cohere": {
        "name": "Cohere",
        "urls": {
            "site": "https://cohere.com/",
            "pricing": "https://cohere.com/pricing",
            "changelog": "https://cohere.com/blog",
        },
    },
    "Amazon Bedrock": {
        "name": "Amazon Bedrock",
        "urls": {
            "site": "https://aws.amazon.com/bedrock/",
            "pricing": "https://aws.amazon.com/bedrock/pricing/",
        },
    },
    "Apple Intelligence": {
        "name": "Apple Intelligence",
        "urls": {
            "site": "https://www.apple.com/apple-intelligence/",
        },
    },
    "Tesla": {
        "name": "Tesla",
        "urls": {
            "site": "https://www.tesla.com/",
            "pricing": "https://www.tesla.com/",
            "careers": "https://www.tesla.com/careers",
        },
    },
    "FedEx": {
        "name": "FedEx",
        "urls": {
            "site": "https://www.fedex.com/",
            "pricing": "https://www.fedex.com/en-us/shipping-rates.html",
            "careers": "https://careers.fedex.com/",
        },
    },
}

# Alias token -> canonical company name (longest aliases first at match time).
_ALIAS_TO_CANONICAL: dict[str, str] = {
    "openai": "OpenAI",
    "chatgpt": "OpenAI",
    "gpt-4": "OpenAI",
    "gpt4": "OpenAI",
    "anthropic": "Anthropic",
    "claude": "Anthropic",
    "google deepmind": "Google DeepMind",
    "deepmind": "Google DeepMind",
    "gemini": "Google AI",
    "google ai": "Google AI",
    "google": "Google AI",
    "perplexity": "Perplexity",
    "microsoft copilot": "Microsoft Copilot",
    "copilot": "Microsoft Copilot",
    "microsoft": "Microsoft Copilot",
    "xai": "xAI",
    "grok": "xAI",
    "cursor": "Cursor",
    "meta ai": "Meta AI",
    "meta": "Meta AI",
    "llama": "Meta AI",
    "mistral": "Mistral",
    "cohere": "Cohere",
    "amazon bedrock": "Amazon Bedrock",
    "bedrock": "Amazon Bedrock",
    "amazon q": "Amazon Bedrock",
    "amazon": "Amazon Bedrock",
    "apple intelligence": "Apple Intelligence",
    "apple": "Apple Intelligence",
    "tesla": "Tesla",
    "tsla": "Tesla",
    "fedex": "FedEx",
    "federal express": "FedEx",
}

_SORTED_ALIASES: list[tuple[str, str]] = sorted(
    _ALIAS_TO_CANONICAL.items(), key=lambda kv: len(kv[0]), reverse=True
)

_TRACKING_RE = re.compile(
    r"\b(track|pulse|watch|monitor|competitors?|companies)\b",
    re.IGNORECASE,
)
_GENERIC_RE = re.compile(
    r"^(?:hi|hello|hey|run|go|start|ok|yes|please|thanks|thank you)\s*[!.?]*$",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s\])}>\"']+", re.IGNORECASE)
_NOTIFY_ON_RE = re.compile(r"\b(notify|alert|slack)\b", re.IGNORECASE)
_NOTIFY_OFF_RE = re.compile(
    r"\b(?:no notify|notify off|don'?t notify|without notify)\b",
    re.IGNORECASE,
)
# Filler phrases that make dumb parse_track_message capture garbage ("a track for Tesla too").
_MESSY_TRACK_RE = re.compile(
    r"\b(?:add|lets?|let's|please)\b|\b(?:a|an|the)\s+(?:track|watch|monitor|pulse)\b|"
    r"\b(?:track|watch|monitor|pulse)\s+(?:a|an|the|for)\b|"
    r"\b(?:too|also|another|as well)\b",
    re.IGNORECASE,
)
_MERGE_RE = re.compile(
    r"\b(?:add|also|too|another|plus|as well)\b",
    re.IGNORECASE,
)


def is_tracking_request(text: str) -> bool:
    return bool(_TRACKING_RE.search(text or ""))


def is_generic_message(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return True
    return bool(_GENERIC_RE.match(stripped))


def is_merge_request(text: str) -> bool:
    """True when the operator wants to add to an existing watchlist."""
    return bool(_MERGE_RE.search(text or ""))


def looks_messy_track_phrase(text: str) -> bool:
    """True for filler-heavy track phrases that need alias/LLM, not dumb regex."""
    return bool(_MESSY_TRACK_RE.search(text or ""))


def parse_notify_from_message(text: str) -> bool | None:
    if _NOTIFY_OFF_RE.search(text or ""):
        return False
    if _NOTIFY_ON_RE.search(text or ""):
        return True
    return None


def _copy_watch_item(canonical: str) -> dict[str, Any]:
    entry = _KNOWN_COMPANIES[canonical]
    return {"name": entry["name"], "urls": dict(entry.get("urls") or {})}


def _find_aliases_in_text(text: str) -> list[str]:
    """Return canonical company names found in text, in order of appearance."""
    lowered = text.lower()
    found: list[str] = []
    seen: set[str] = set()
    for alias, canonical in _SORTED_ALIASES:
        pattern = re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)
        for match in pattern.finditer(lowered):
            if canonical not in seen:
                found.append((match.start(), canonical))
                seen.add(canonical)
    found.sort(key=lambda x: x[0])
    return [name for _, name in found]


def _extract_freeform_names(text: str) -> list[str]:
    """Pull candidate names from track/pulse/watch patterns and comma lists."""
    names: list[str] = []
    for pattern in (
        r"(?:track|pulse on|pulse|watch|monitor)\s+(.+?)(?:\s+for\s+\S+)?(?:[.!?]|$)",
        r"(?:competitors?|companies)\s*(?:are|:)?\s*(.+?)(?:[.!?]|$)",
    ):
        for match in re.finditer(pattern, text, re.IGNORECASE):
            chunk = match.group(1).strip()
            chunk = re.sub(r"\s+for\s+.+$", "", chunk, flags=re.IGNORECASE)
            parts = re.split(r"\s*,\s*|\s+and\s+|\s+or\s+", chunk)
            for part in parts:
                cleaned = part.strip(" .\"'")
                if cleaned and len(cleaned) >= 2:
                    names.append(cleaned)
    return names


def _resolve_name_to_canonical(name: str) -> str | None:
    key = name.strip().lower()
    if key in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[key]
    for alias, canonical in _SORTED_ALIASES:
        if key == alias or key in alias or alias in key:
            return canonical
    return None


def _attach_urls(watchlist: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    urls = _URL_RE.findall(text)
    if not urls:
        return watchlist

    out = [{**item, "urls": dict(item.get("urls") or {})} for item in watchlist]
    if len(out) == 1:
        urls_dict = out[0]["urls"]
        if not urls_dict.get("site"):
            urls_dict["site"] = urls[0]
        for url in urls[1:]:
            lower = url.lower()
            if "pricing" in lower and "pricing" not in urls_dict:
                urls_dict["pricing"] = url
            elif any(k in lower for k in ("changelog", "blog", "news")) and "changelog" not in urls_dict:
                urls_dict["changelog"] = url
            elif "career" in lower and "careers" not in urls_dict:
                urls_dict["careers"] = url
        return out

    for url in urls:
        host = re.sub(r"^https?://(www\.)?", "", url.lower()).split("/")[0]
        for item in out:
            name_slug = re.sub(r"[^a-z0-9]", "", item["name"].lower())
            if name_slug and name_slug in re.sub(r"[^a-z0-9]", "", host):
                urls_dict = item["urls"]
                if not urls_dict.get("site"):
                    urls_dict["site"] = url
                break
    return out


def _offline_watchlist(text: str) -> list[dict[str, Any]]:
    canonicals = _find_aliases_in_text(text)
    if not canonicals:
        for raw in _extract_freeform_names(text):
            resolved = _resolve_name_to_canonical(raw)
            if resolved and resolved not in canonicals:
                canonicals.append(resolved)

    if not canonicals:
        return []

    watchlist = [_copy_watch_item(name) for name in canonicals]
    return _attach_urls(watchlist, text)


def _llm_parse_enabled() -> bool:
    """LLM watchlist extract is ON by default when an API key is present.

    Kill-switch: ``COMPETITOR_PULSE_LLM_PARSE=0`` (or false/off/no) forces offline only.
    """
    import os

    flag = (os.environ.get("COMPETITOR_PULSE_LLM_PARSE") or "").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    return True


def _parse_competitors_json(content: str) -> list[dict[str, Any]] | None:
    content = (content or "").strip()
    if not content:
        return None
    fence = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
    if fence:
        content = fence.group(1).strip()
    brace = re.search(r"\{.*\}", content, re.DOTALL)
    if brace:
        content = brace.group(0)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    raw_list = None
    if isinstance(parsed, dict):
        raw_list = parsed.get("competitors") or parsed.get("watchlist")
    if not isinstance(raw_list, list):
        return None
    cleaned: list[dict[str, Any]] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        # Reject filler garbage names from bad extractions.
        lowered = name.lower()
        if lowered in {"a track", "track", "watch", "monitor", "pulse", "competitors"}:
            continue
        if lowered.startswith("a track for") or lowered.startswith("a watch for"):
            continue
        urls = item.get("urls") if isinstance(item.get("urls"), dict) else {}
        cleaned.append({"name": name, "urls": {k: str(v) for k, v in urls.items() if v}})
    return cleaned or None


def _llm_watchlist(text: str) -> list[dict[str, Any]] | None:
    """Extract competitors via direct HTTP chat_completions (stream:false).

    Never uses ``get_llm()`` / ``llm.invoke`` — MARS concatenates those streams
    into doctl ``text``. ON by default when an API key is present; set
    ``COMPETITOR_PULSE_LLM_PARSE=0`` to force offline-only.
    """
    if not _llm_parse_enabled():
        return None
    try:
        from competitor_pulse.intent_llm import chat_completions
        from competitor_pulse.llm import harness_env_available

        if not harness_env_available():
            return None

        system = (
            "Extract companies the user wants to track/watch/pulse/monitor. "
            "Return ONLY valid JSON (no markdown prose): "
            '{"competitors":[{"name":"Company","urls":{"site":"https://...","pricing":"https://...","changelog":"https://...","careers":"https://..."}}]}. '
            "Use real public company names (e.g. Tesla, FedEx), never filler phrases "
            "like 'a track for …'. Include best-effort HTTPS URLs when obvious. "
            'If no companies, return {"competitors":[]}.'
        )
        content = chat_completions(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            temperature=0.0,
            max_tokens=500,
        )
        if not content:
            return None
        return _parse_competitors_json(content)
    except Exception:
        return None


def parse_watchlist_from_message(text: str) -> dict[str, Any]:
    """Parse natural-language intake into competitor list metadata.

    Returns dict with keys:
      competitors: list[dict] (may be empty)
      notify: bool | None
      is_tracking_request: bool
      is_generic: bool
      is_merge: bool
      source: "offline" | "llm" | "none"

    Prefer offline aliases. When empty or the phrase looks messy (filler like
    "add a track for …"), call LLM extract via ``intent_llm.chat_completions``
    (stream:false) — never ``get_llm``/``llm.invoke``. Kill-switch
    ``COMPETITOR_PULSE_LLM_PARSE=0`` forces offline only. Never call the LLM for
    generic/chat messages.
    """
    stripped = (text or "").strip()
    result: dict[str, Any] = {
        "competitors": [],
        "notify": parse_notify_from_message(stripped),
        "is_tracking_request": is_tracking_request(stripped),
        "is_generic": is_generic_message(stripped),
        "is_merge": is_merge_request(stripped),
        "source": "none",
    }

    if not stripped:
        return result

    # Chat/help/banter must not invoke the watchlist LLM.
    if result["is_generic"] or not result["is_tracking_request"]:
        return result

    offline = _offline_watchlist(stripped)
    if offline:
        # Alias map wins even for filler phrases ("add a track for Tesla too").
        result["competitors"] = offline
        result["source"] = "offline"
        return result

    # Empty / unknown names: LLM extract (stream:false) when enabled + key present.
    # Filler phrases ("add a track for …") are rejected by parse_track_message;
    # prefer LLM here over inventing garbage company names.
    llm_list = _llm_watchlist(stripped)
    if llm_list:
        result["competitors"] = _attach_urls(llm_list, stripped)
        result["source"] = "llm"
        return result

    return result
