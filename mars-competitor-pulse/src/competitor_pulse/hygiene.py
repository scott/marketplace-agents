"""Final-message hygiene — Ghost Writer-style clean before deliver.

Deterministic; no LLM. Canonical rules: Shop design/PULSE-PERSONA-COPY.md §8.
"""

from __future__ import annotations

import re

# Em/en dash and spaced double-hyphen → sentence punctuation.
_EMDASH_RE = re.compile(r"\s*[—–]\s*")
_DOUBLE_HYPHEN_RE = re.compile(r"\s+--\s+")
_DOUBLED_COMMA_RE = re.compile(r",\s*,+")

# Accidental fenced JSON / state dumps.
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*\n?.*?```", re.DOTALL | re.IGNORECASE)
_WATCHLIST_BLOB_RE = re.compile(
    r'\{\s*"(?:watchlist|competitors)"\s*:\s*\[.*?\]\s*\}',
    re.DOTALL,
)

# Stage / status label soup at line start.
_LABEL_PREFIX_RE = re.compile(
    r"(?mi)^(?:intake|plan|gather|analyze|draft|ask|act|report|converse)\s*:\s*",
)
_STATUS_LINE_RE = re.compile(
    r"(?mi)^status:\s*(?:ok|empty|blocked|baseline|denied|notified)\s*$",
)

# Kill-list substrings that must never reach chat.
_KILL_SUBSTRINGS = (
    "review site_copy_change",
    "review pricing_change",
    "review changelog_change",
    "review careers_change",
)

_COUNTER_PREFIX_RE = re.compile(
    r"(?mi)^(?:[-*]\s*)?Counter\s+\S+/\S+:\s*review\s+\S+\s*[—–-]?\s*",
)
_CHANGE_TYPE_ENUM_RE = re.compile(
    r"\breview\s+(?:site_copy_change|pricing_change|changelog_change|careers_change)\b",
    re.IGNORECASE,
)

_HELPDesk_OPENERS = re.compile(
    r"(?mi)^(Certainly,|Of course,|I'd be happy to|I would be happy to|Let me\s+)",
)


def hygiene_text(text: str, *, preserve_markdown: bool = True) -> str:
    """Strip accidental JSON fences, stage labels, em-dashes; kill label soup.

    Does not alter intentional markdown headings from the brief shape when
    ``preserve_markdown`` is True (default). Evidence URLs are left intact.
    """
    if not text:
        return text or ""

    out = text
    out = _FENCED_JSON_RE.sub("", out)
    out = _WATCHLIST_BLOB_RE.sub("", out)
    out = _COUNTER_PREFIX_RE.sub("- ", out)
    out = _CHANGE_TYPE_ENUM_RE.sub("page change", out)
    for needle in _KILL_SUBSTRINGS:
        out = re.sub(re.escape(needle), "page change", out, flags=re.IGNORECASE)

    # Em/en dash and " -- " → ", " then collapse doubled commas.
    out = _EMDASH_RE.sub(", ", out)
    out = _DOUBLE_HYPHEN_RE.sub(", ", out)
    out = _DOUBLED_COMMA_RE.sub(", ", out)

    lines: list[str] = []
    for line in out.splitlines():
        cleaned = _LABEL_PREFIX_RE.sub("", line)
        if _STATUS_LINE_RE.match(cleaned.strip()):
            continue
        cleaned = _HELPDesk_OPENERS.sub("", cleaned)
        # Drop leftover "Counter " prefix lines (implication bullets must not use it).
        if re.match(r"^(?:[-*]\s*)?Counter\s+", cleaned.strip()):
            cleaned = re.sub(r"^(?:[-*]\s*)?Counter\s+", "- ", cleaned.strip())
        lines.append(cleaned)
    out = "\n".join(lines)

    # Collapse excessive blank lines from removals.
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()
