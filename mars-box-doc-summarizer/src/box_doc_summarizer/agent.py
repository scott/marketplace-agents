"""Conversational intake: an LLM tool-calling loop on DO Serverless Inference.

The model talks naturally and decides when to call one of three tools:

- ``list_folders``: executed inline (read-only Box API); the result goes back to
  the model so it can resolve names and answer.
- ``list_files(folder)`` and ``summarize_folder(folder)``: terminal. They hand a
  resolved folder id to the graph, which runs the mount-first pipeline. A
  summary still stops at the HITL approval interrupt before any write.

Nothing here summarizes on its own: a default folder id is only used when the
model calls ``summarize_folder``/``list_files`` without naming a folder.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from box_doc_summarizer.llm import chat_with_tools

MAX_STEPS = 4
HISTORY = 16

AGENT_PROMPT = """You are Box Doc Summarizer, a friendly, sharp colleague who lives next to a shared Box folder. Your voice is warm and easygoing, a little playful, never stiff: short sentences, contractions, plain words. No helpdesk filler, no em-dashes, no JSON or stage dumps in chat.

What you can do, via tools:
- list_folders: see every Box folder you have access to (names, paths, ids). Call it whenever you need to find or resolve a folder name the user mentioned, or when they ask what folders you can see.
- list_files(folder): show what's inside one folder (read-only).
- summarize_folder(folder): read every doc in a folder and draft an executive summary with links to each source. The user approves before anything is written back to Box.

Rules:
- Only call summarize_folder when the user clearly asks for a summary, brief, digest, or refresh in this turn (follow-ups like "summarize it" count, using the folder from the conversation). Listing, browsing, greetings, and questions never trigger a summary.
- Pass a folder id when you know it (from list_folders or the conversation). If the user names a folder you haven't resolved yet, call list_folders first.
- If you can't tell which folder they mean, ask. Don't guess between similar names.
- Never invent folders, files, or numbers.
- For anything else, just chat and keep it short. If asked what you can do, explain the three things above in a couple of friendly lines.
{default_note}"""

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_folders",
            "description": "List the Box folders this agent can access (path and id). Read-only.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List the files inside one Box folder. Read-only. Use a folder id when known, otherwise its name.",
            "parameters": {
                "type": "object",
                "properties": {"folder": {"type": "string", "description": "Folder id or exact folder name."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_folder",
            "description": "Draft an executive summary of every document in one Box folder. The user must approve before it is saved. Only call when the user explicitly asks for a summary.",
            "parameters": {
                "type": "object",
                "properties": {"folder": {"type": "string", "description": "Folder id or exact folder name. Omit to use the default folder."}},
            },
        },
    },
]


@dataclass
class AgentResult:
    action: str  # reply | list_files | summarize | offline
    reply: str = ""
    folder: str = ""
    notes: list[str] = field(default_factory=list)


def _content(m: Any) -> str:
    c = getattr(m, "content", None) if not isinstance(m, dict) else m.get("content")
    return c if isinstance(c, str) else str(c or "")


def history_messages(messages: list[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in (messages or [])[-HISTORY:]:
        if isinstance(m, ToolMessage):
            continue
        role = None
        if isinstance(m, HumanMessage):
            role = "user"
        elif isinstance(m, AIMessage):
            role = "assistant"
        elif isinstance(m, dict):
            r = (m.get("type") or m.get("role") or "").lower()
            role = {"human": "user", "user": "user", "ai": "assistant", "assistant": "assistant"}.get(r)
        text = _content(m)
        if role and text.strip():
            if role == "assistant" and len(text) > 1500:
                text = text[:1500] + "\n…(trimmed)"
            out.append({"role": role, "content": text})
    return out


def run_agent(messages: list[Any] | None, *, list_folders_fn, default_folder: str = "") -> AgentResult:
    """Run the tool loop. ``list_folders_fn()`` returns [(path, id), ...]."""
    note = (
        f"Default folder id (use ONLY if the user asks to summarize or list files without naming a folder): {default_folder}"
        if default_folder
        else "There is no default folder; ask which folder if the user doesn't name one."
    )
    convo: list[dict[str, Any]] = [{"role": "system", "content": AGENT_PROMPT.format(default_note=note)}]
    convo += history_messages(messages)
    notes: list[str] = []
    for _ in range(MAX_STEPS):
        msg = chat_with_tools(convo, TOOLS)
        if msg is None:
            return AgentResult("offline", notes=notes)
        calls = msg.get("tool_calls") or []
        if not calls:
            return AgentResult("reply", reply=(msg.get("content") or "").strip(), notes=notes)
        convo.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for call in calls:
            fn = (call.get("function") or {})
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}") or {}
            except (TypeError, ValueError):
                args = {}
            folder = str(args.get("folder") or "").strip()
            if name == "summarize_folder":
                notes.append(f"agent: summarize_folder({folder or 'default'})")
                return AgentResult("summarize", folder=folder, notes=notes)
            if name == "list_files":
                notes.append(f"agent: list_files({folder or 'default'})")
                return AgentResult("list_files", folder=folder, notes=notes)
            if name == "list_folders":
                try:
                    rows = list_folders_fn()
                    result = json.dumps([{"path": p, "id": i} for p, i in rows])
                    notes.append(f"agent: list_folders -> {len(rows)}")
                except Exception as exc:  # noqa: BLE001
                    result = json.dumps({"error": str(exc)[:200]})
                    notes.append("agent: list_folders failed")
            else:
                result = json.dumps({"error": f"unknown tool {name}"})
            convo.append({"role": "tool", "tool_call_id": call.get("id") or name, "content": result})
    return AgentResult("reply", reply="I went in circles on that one. Mind rephrasing?", notes=notes)


def default_folder_id(state_folder: str = "") -> str:
    return (state_folder or os.environ.get("BOX_FOLDER_ID", "")).strip()
