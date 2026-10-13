"""Final-message hygiene — Ghost Writer-style clean before deliver.

Deterministic; no LLM.
"""

from __future__ import annotations

import re

_EMDASH_RE = re.compile(r"\s*[—–]\s*")
_RANGE_DASH_RE = re.compile(r"(\d)\s*[–—]\s*([$€£]?\d)")
_WORD_RANGE_RE = re.compile(r"(\w)–(\w)")
_DOUBLE_HYPHEN_RE = re.compile(r"\s+--\s+")
_DOUBLED_COMMA_RE = re.compile(r",\s*,+")
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*\n?.*?```", re.DOTALL | re.IGNORECASE)
_LABEL_PREFIX_RE = re.compile(
    r"(?mi)^(?:intake|connect|inventory|extract|brief|links|synthesize|ask|write_back|report)\s*:\s*",
)
_STATUS_LINE_RE = re.compile(
    r"(?mi)^status:\s*(?:ok|empty|blocked|denied|written|summarized)\s*$",
)
_HELPDesk_OPENERS = re.compile(
    r"(?mi)^(Certainly,|Of course,|I'd be happy to|I would be happy to|Let me\s+)",
)


def hygiene_text(text: str, *, preserve_markdown: bool = True) -> str:
    """Strip accidental JSON fences, stage labels, em-dashes; kill label soup."""
    if not text:
        return text or ""

    out = text
    out = _FENCED_JSON_RE.sub("", out)
    out = _RANGE_DASH_RE.sub(r"\1-\2", out)
    out = _WORD_RANGE_RE.sub(r"\1 to \2", out)  # June–November -> June to November  # keep numeric ranges (60–120 -> 60-120)
    out = _EMDASH_RE.sub(", ", out)
    out = _DOUBLE_HYPHEN_RE.sub(", ", out)
    out = _DOUBLED_COMMA_RE.sub(", ", out)

    lines: list[str] = []
    for line in out.splitlines():
        cleaned = _LABEL_PREFIX_RE.sub("", line)
        if _STATUS_LINE_RE.match(cleaned.strip()):
            continue
        cleaned = _HELPDesk_OPENERS.sub("", cleaned)
        lines.append(cleaned)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()
