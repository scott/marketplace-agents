"""Chat intent + Box folder reference parsing (regex fast path; no LLM needed).

Intents: chat | help | list_folders | list_files | summarize.
List intents win over summarize whenever the message says list/show/what's in,
even if it also contains a numeric folder id.
"""

from __future__ import annotations

import re

_FOLDER_URL_RE = re.compile(r"box\.com/(?:folder|s/[^/\s]+/folder)/(\d+)", re.I)
_FOLDER_ID_RE = re.compile(r"\bfolder\s*(?:id\s*)?[:#]?\s*(\d{3,})\b", re.I)
_BARE_ID_RE = re.compile(r"\b(\d{6,})\b")
_HELP_RE = re.compile(r"^\s*(help|\?|what can you do|how does (this|it) work)", re.I)
_HI_RE = re.compile(r"^\s*(hi|hey|hello|yo|good (morning|afternoon|evening))\b[\s!.]*$", re.I)
_SUMMARIZE_RE = re.compile(r"\b(summari[sz]e|brief|digest|exec(utive)? summary|refresh|re-?run|run)\b", re.I)
_LIST_FOLDERS_RE = re.compile(
    r"\b(list|show|which|what)\b[^.?!]*\bfolders\b|\bfolders\b[^.?!]*\b(can you see|do you see|available|visible)\b",
    re.I,
)
_LIST_FILES_RE = re.compile(
    r"\b(list|show)\b[^.?!]*\b(files?|docs?|documents?|contents?)\b|\bwhat(?:'|’)?s\s+in\b|\bwhat is in\b|\bcontents of\b",
    re.I,
)
_LIST_ANY_RE = re.compile(r"\b(list|show|what(?:'|’)?s in|what is in)\b", re.I)
_NAME_AFTER_RE = re.compile(
    r"(?:summari[sz]e|brief|digest|run|refresh|list files in|list files for|list documents in|"
    r"show files in|show me what(?:'|’)?s in|what(?:'|’)?s in|what is in|contents of|files in)\s+"
    r"(?:me\s+(?:on|about)\s+)?"
    r"(?:the\s+)?(?:box\s+)?(?:folder\s+)?(?:called\s+|named\s+)?[\"'“]?([^\"'”?!]+?)[\"'”]?\s*(?:folder)?\s*[?.!]*$",
    re.I,
)
_NOT_A_NAME = {"", "it", "this", "that", "folder", "the folder", "files", "everything", "again", "now", "my folder", "please"}


def parse_folder_id(text: str) -> str:
    if not text:
        return ""
    for rx in (_FOLDER_URL_RE, _FOLDER_ID_RE, _BARE_ID_RE):
        m = rx.search(text)
        if m:
            return m.group(1)
    return ""


def parse_folder_name(text: str) -> str:
    """Folder name after a command verb, e.g. 'summarize Hawaii Trip' -> 'Hawaii Trip'."""
    if not text or parse_folder_id(text):
        return ""
    m = _NAME_AFTER_RE.search(text.strip())
    if not m:
        return ""
    name = m.group(1).strip().strip(".")
    low = name.lower()
    if low in _NOT_A_NAME or low.split()[0] in {"my", "our", "your", "all"}:
        return ""
    return name


def classify_intent(text: str) -> str:
    t = (text or "").strip()
    if not t or _HI_RE.match(t):
        return "chat"
    if _HELP_RE.match(t):
        return "help"
    if _LIST_FOLDERS_RE.search(t):
        return "list_folders"
    if _LIST_FILES_RE.search(t):
        return "list_files"
    if _LIST_ANY_RE.search(t):
        return "chat"  # list/show phrasing never triggers a summary run
    if parse_folder_id(t) or _SUMMARIZE_RE.search(t):
        return "summarize"
    return "chat"
