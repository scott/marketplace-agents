"""Stage nodes: intake → connect → inventory → extract → brief → links → synthesize → ask → write_back → report."""

from __future__ import annotations

import os
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from box_doc_summarizer import box_api, box_mount
from box_doc_summarizer.agent import run_agent
from box_doc_summarizer.extractors import extract_bytes, is_supported
from box_doc_summarizer.hygiene import hygiene_text
from box_doc_summarizer.intent import classify_intent, parse_folder_id, parse_folder_name
from box_doc_summarizer.llm import chat_completion, harness_env_available, last_error, parse_json_object
from box_doc_summarizer.persona import (
    BRIEF_INSTRUCTIONS,
    SYNTH_INSTRUCTIONS,
    SYSTEM_PROMPT,
    ambiguous_folder_message,
    ask_body,
    ask_title,
    files_message,
    folders_message,
    no_folder_match_message,
    blocked_message,
    denied_message,
    empty_message,
    help_message,
    missing_folder_message,
    welcome_message,
    write_failed_message,
    written_message,
)
from box_doc_summarizer.state import SummarizerState

ASSISTANT_DISPLAY_NAME = "Box Doc Summarizer"
_CONFLICT_RE = re.compile(r"(\(conflict|conflicted copy|\(\d+\)\.\w+$)", re.I)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def summary_filename() -> str:
    return os.environ.get("SUMMARY_FILENAME", "EXECUTIVE-SUMMARY.md")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _append(state: SummarizerState, line: str) -> list[str]:
    return [*(state.get("stage_summaries") or []), line]


def _human_text(messages: list[Any] | None) -> str:
    for msg in reversed(messages or []):
        if isinstance(msg, HumanMessage):
            return msg.content if isinstance(msg.content, str) else str(msg.content)
        if isinstance(msg, dict) and (msg.get("type") or msg.get("role") or "").lower() in {"human", "user"}:
            return str(msg.get("content") or "")
    return ""


def _reply(text: str) -> dict[str, Any]:
    return {"messages": [AIMessage(content=hygiene_text(text or ""), name=ASSISTANT_DISPLAY_NAME)]}


def _normalize_decision(raw: Any) -> str:
    if isinstance(raw, dict):
        if "approved" in raw:
            return "approve" if raw.get("approved") else "deny"
        raw = raw.get("decision") or raw.get("value") or raw.get("choice") or "deny"
    if isinstance(raw, bool):
        return "approve" if raw else "deny"
    s = str(raw).strip().lower()
    return "approve" if s in {"approve", "approved", "yes", "y", "ok", "okay", "true"} else "deny"


def _mars_node(fn):
    def wrapped(state):
        out = fn(state)
        return {k: v for k, v in (out or {}).items() if k != "human_summary"} if out else out

    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped


def _skip_name(name: str) -> str:
    parts = name.split("/")
    base = parts[-1]
    if any(p.startswith(".") for p in parts) or base.startswith("~$"):
        return "hidden or temp file"
    if base == summary_filename():
        return "our own summary"
    if _CONFLICT_RE.search(base):
        return "Box conflict copy"
    return ""


# ---------------------------------------------------------------------------
# intake
# ---------------------------------------------------------------------------


def _visible_folders() -> tuple[list[Any], bool]:
    limit = _int_env("MAX_LIST_FOLDERS", 200)
    items = box_api.get_box_client().list_folders("0", max_depth=_int_env("MAX_FOLDER_DEPTH", 3), max_items=limit)
    return items, len(items) >= limit


def resolve_folder_name(name: str) -> tuple[str, str]:
    """Return (folder_id, reply_if_unresolved). Case-insensitive on folder name or path."""
    import difflib

    if not box_api.box_api_configured():
        return "", f"I can't look up folder names without BOX_JWT_CONFIG_JSON. Send the folder id instead."
    try:
        folders, _ = _visible_folders()
    except Exception as exc:  # noqa: BLE001
        return "", f"I couldn't list folders ({str(exc)[:160]}). Send the folder id instead."
    key = name.strip().lower()
    exact = [f for f in folders if f.name.lower() == key or f.path.lower() == key]
    if len(exact) == 1:
        return exact[0].id, ""
    if len(exact) > 1:
        return "", ambiguous_folder_message(name, [(f.path, f.id) for f in exact])
    names = {f.name.lower(): f for f in folders}
    close = difflib.get_close_matches(key, list(names), n=5, cutoff=0.5)
    contains = [f for f in folders if key in f.name.lower() and f.name.lower() not in close]
    picks = [names[c] for c in close] + contains[: max(0, 5 - len(close))]
    return "", no_folder_match_message(name, [(f.path, f.id) for f in picks])


_CLEAR = {"folder_id": "", "fixture_path": ""}  # per-run inputs never leak into the next chat turn


def _pending_human_text(messages: list[Any] | None) -> str:
    """Text of the newest message only if it is a user turn not yet answered."""
    if not messages:
        return ""
    last = messages[-1]
    if isinstance(last, HumanMessage) or (
        isinstance(last, dict) and (last.get("type") or last.get("role") or "").lower() in {"human", "user"}
    ):
        return _human_text([last])
    return ""


def _folder_rows() -> list[tuple[str, str]]:
    if not box_api.box_api_configured():
        raise RuntimeError("BOX_JWT_CONFIG_JSON is not set, so I can't see Box folders")
    folders, _ = _visible_folders()
    return [(f.path, f.id) for f in folders]


def _chat(state: SummarizerState, text: str, notes: list[str] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"intent": "chat", "status": "chat", **_CLEAR, **_reply(text)}
    if notes:
        out["stage_summaries"] = [*(state.get("stage_summaries") or []), *notes]
    return out


def _start(state: SummarizerState, intent: str, folder_ref: str, fixture: str, default: str, notes: list[str]) -> dict[str, Any]:
    """Resolve a folder reference (id or name) and hand off to connect."""
    ref = (folder_ref or "").strip()
    folder_id = ""
    if ref.isdigit():
        folder_id = ref
    elif ref:
        folder_id = parse_folder_id(ref)
        if not folder_id:
            folder_id, unresolved = resolve_folder_name(ref)
            if unresolved:
                return _chat(state, unresolved, notes)
    folder_id = folder_id or default
    if not folder_id and not fixture:
        return _chat(state, missing_folder_message(), notes)
    return {
        "intent": intent,
        "folder_id": folder_id,
        "fixture_path": fixture if (fixture and (not ref or folder_id == default)) else "",
        "documents": [],
        "skipped": [],
        "status": "",
        "stage_summaries": [*(state.get("stage_summaries") or []), *notes, f"intake: {intent} folder {folder_id or 'fixture'}"],
    }


def _offline_intake(state: SummarizerState, text: str, fixture: str, default: str) -> dict[str, Any]:
    """Regex fallback when the LLM is unavailable. List/show never summarizes."""
    note = [f"intake: offline regex fallback ({last_error() or 'LLM unavailable'})"]
    intent = classify_intent(text)
    if intent == "help":
        return {"intent": "help", "status": "help", **_CLEAR, **_reply(help_message())}
    if intent == "chat":
        return _chat(state, welcome_message(), note)
    if intent == "list_folders":
        try:
            rows = _folder_rows()
        except Exception as exc:  # noqa: BLE001
            return {"intent": intent, "status": "blocked", **_CLEAR, **_reply(blocked_message(str(exc)[:300]))}
        return {
            "intent": intent,
            "status": "listed",
            **_CLEAR,
            "stage_summaries": _append(state, f"list_folders: {len(rows)} via Box API (read-only)"),
            **_reply(folders_message(rows, len(rows) >= _int_env("MAX_LIST_FOLDERS", 200))),
        }
    ref = parse_folder_id(text) or parse_folder_name(text)
    return _start(state, intent, ref, fixture, default, note)


def intake(state: SummarizerState) -> dict[str, Any]:
    messages = state.get("messages")
    text = _pending_human_text(messages)
    fixture = (state.get("fixture_path") or "").strip()
    input_folder = (state.get("folder_id") or "").strip()  # this run's input only (cleared after each run)
    default = input_folder or os.environ.get("BOX_FOLDER_ID", "").strip()

    if not text.strip():
        # Programmatic run (trigger / webhook / fixture) with no chat turn.
        if fixture or input_folder:
            return _start(state, "summarize", input_folder, fixture, default, [])
        return {"intent": "chat", "status": "chat", **_CLEAR, **_reply(welcome_message())}

    if not harness_env_available():
        return _offline_intake(state, text, fixture, default)
    res = run_agent(messages, list_folders_fn=_folder_rows, default_folder=default)
    if res.action == "offline":
        return _offline_intake(state, text, fixture, default)
    if res.action == "reply":
        return _chat(state, res.reply or welcome_message(), res.notes)
    return _start(state, res.action, res.folder, fixture, default, res.notes)


def route_after_intake(state: SummarizerState) -> str:
    return "connect" if state.get("intent") in {"summarize", "list_files"} else "end"


# ---------------------------------------------------------------------------
# connect (fixture | optional Box Mount | Box API)
# ---------------------------------------------------------------------------


def connect(state: SummarizerState) -> dict[str, Any]:
    fixture = state.get("fixture_path") or ""
    folder_id = state.get("folder_id") or ""
    if fixture:
        root = Path(fixture)
        if not root.is_dir():
            return {"status": "blocked", "blocked_reason": f"fixture folder {fixture} not found", "mount_state": "skipped"}
        return {
            "source_mode": "fixture",
            "local_root": str(root),
            "folder_name": root.name,
            "folder_url": box_api.folder_url(folder_id) if folder_id else root.resolve().as_uri(),
            "mount_state": "skipped",
            "stage_summaries": _append(state, "connect: fixture"),
        }

    folder_name, folder_link = f"Box folder {folder_id}", box_api.folder_url(folder_id)
    allow_api = os.environ.get("BOX_ALLOW_API_FALLBACK", "0").strip() == "1"
    mount_fail = None
    if box_mount.mount_enabled():
        res = box_mount.ensure_mount(folder_id)
        notes = [f"connect: mount step: {x}" for x in res.steps]
        if res.ok:
            if box_api.box_api_configured():
                try:  # folder name + link only; reads/writes go through the mount
                    f = box_api.get_box_client().get_folder(folder_id)
                    folder_name, folder_link = f.name, f.url
                except Exception:  # noqa: BLE001
                    pass
            prev = list(state.get("stage_summaries") or [])
            return {
                "source_mode": "mount",
                "local_root": res.path,
                "folder_name": folder_name,
                "folder_url": folder_link,
                "mount_state": res.state,
                "mount_steps": res.steps,
                "stage_summaries": prev + notes + [f"connect: source_mode=mount ({res.state}) at {res.path}"],
            }
        if not allow_api:
            return {
                "status": "blocked",
                "blocked_reason": f"Box Mount: {res.message}",
                "mount_state": res.state,
                "mount_steps": res.steps,
                "source_mode": "mount",
            }
        mount_fail = res

    mount_state = f"failed: {mount_fail.message}"[:200] if mount_fail else "skipped"
    if not box_api.box_api_configured():
        return {"status": "blocked", "blocked_reason": "BOX_JWT_CONFIG_JSON is not set.", "mount_state": mount_state}
    try:
        folder = box_api.get_box_client().get_folder(folder_id)
    except Exception as exc:  # noqa: BLE001
        reason = str(exc)[:300]
        if mount_fail:
            reason = f"Box Mount: {mount_fail.message}. Box API fallback: {reason}"[:400]
        return {"status": "blocked", "blocked_reason": reason, "mount_state": mount_state}
    line = "connect: source_mode=api" + (" (explicit BOX_ALLOW_API_FALLBACK=1 after mount failure)" if mount_fail else "")
    return {
        "source_mode": "api",
        "folder_name": folder.name,
        "folder_url": folder.url,
        "mount_state": mount_state,
        "stage_summaries": _append(state, line),
    }


def route_after_connect(state: SummarizerState) -> str:
    if state.get("status") == "blocked":
        return "report"
    return "list_files" if state.get("intent") == "list_files" else "inventory"


def list_files(state: SummarizerState) -> dict[str, Any]:
    """Read-only listing of the connected folder (mount path or explicit API mode)."""
    mode = state.get("source_mode") or ""
    files: list[dict[str, Any]] = []
    if mode == "api":
        try:
            for i in box_api.get_box_client().list_files(state["folder_id"], max_depth=_int_env("MAX_DEPTH", 3)):
                if not _skip_name(i.path) or i.path == summary_filename():
                    files.append({"path": i.path, "size": i.size})
        except Exception as exc:  # noqa: BLE001
            return {"status": "blocked", "blocked_reason": str(exc)[:300], **_CLEAR, **_reply(blocked_message(str(exc)[:300]))}
    else:
        root = Path(state["local_root"])
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if any(part.startswith(".") for part in rel.split("/")):
                continue
            files.append({"path": rel, "size": p.stat().st_size})
    for f in files:
        ext = os.path.splitext(f["path"])[1].lstrip(".").lower()
        f["type"] = ext or "file"
    name = state.get("folder_name") or f"folder {state.get('folder_id')}"
    return {
        "status": "listed",
        **_CLEAR,
        "stage_summaries": _append(state, f"list_files: {len(files)} files (source_mode={mode})"),
        **_reply(files_message(name, files, mode)),
    }


# ---------------------------------------------------------------------------
# inventory
# ---------------------------------------------------------------------------


def inventory(state: SummarizerState) -> dict[str, Any]:
    max_files = _int_env("MAX_FILES", 50)
    max_bytes = _int_env("MAX_FILE_BYTES", 25 * 1024 * 1024)
    docs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    existing_summary_id = ""

    if state.get("source_mode") == "api":
        try:
            items = box_api.get_box_client().list_files(
                state["folder_id"], max_depth=_int_env("MAX_DEPTH", 3), max_items=max_files * 4
            )
        except Exception as exc:  # noqa: BLE001
            return {"status": "blocked", "blocked_reason": str(exc)[:300]}
        entries = [
            {"path": i.path, "name": i.name, "file_id": i.id, "size": i.size, "modified": i.modified_at, "url": i.url}
            for i in items
        ]
        for i in items:
            if i.path == summary_filename():
                existing_summary_id = i.id
    else:
        root = Path(state["local_root"])
        entries = []
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if any(part.startswith(".") for part in rel.split("/")[:-1]):
                continue
            st = p.stat()
            entries.append(
                {
                    "path": rel,
                    "name": p.name,
                    "file_id": "",
                    "size": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
                    "url": "",
                }
            )

    for e in sorted(entries, key=lambda x: x["path"].lower()):
        reason = _skip_name(e["path"])
        if not reason and e["size"] > max_bytes:
            reason = "over size cap"
        if not reason and len(docs) >= max_files:
            reason = f"over MAX_FILES ({max_files})"
        if reason:
            skipped.append({**e, "reason": reason})
            continue
        e["supported"] = is_supported(e["name"])
        docs.append(e)

    if not docs:
        return {"status": "empty", "documents": [], "skipped": skipped}
    return {
        "documents": docs,
        "skipped": skipped,
        "existing_summary_id": existing_summary_id,
        "stage_summaries": _append(
            state,
            f"inventory: {len(docs)} docs, {len(skipped)} skipped"
            + (f" (read from mount path {state.get('local_root')})" if state.get("source_mode") == "mount" else ""),
        ),
    }


def route_after_inventory(state: SummarizerState) -> str:
    return "report" if state.get("status") in {"blocked", "empty"} else "extract"


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------


def extract(state: SummarizerState) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    client = box_api.get_box_client() if state.get("source_mode") == "api" else None
    root = Path(state.get("local_root") or ".")
    for d in state.get("documents") or []:
        d = dict(d)
        if not d.get("supported"):
            d.update(text="", note="metadata only (unsupported type)")
            out.append(d)
            continue
        try:
            data = client.download(d["file_id"]) if client else (root / d["path"]).read_bytes()
            ex = extract_bytes(d["name"], data)
            d.update(text=ex.text, supported=ex.supported, truncated=ex.truncated)
            if ex.error:
                d["note"] = f"could not read ({ex.error})"
        except Exception as exc:  # noqa: BLE001
            d.update(text="", supported=False, note=f"download failed ({str(exc)[:120]})")
        out.append(d)
    return {"documents": out, "stage_summaries": _append(state, "extract: done")}


# ---------------------------------------------------------------------------
# brief
# ---------------------------------------------------------------------------

_SENT_RE = re.compile(r"(?<=[.!?])\s+")


def _strip_md(line: str) -> str:
    return re.sub(r"[*_`>#]+", "", line).strip()


def heuristic_brief(text: str) -> tuple[str, list[str]]:
    lines = [ln.rstrip() for ln in text.splitlines()]
    headings = [_strip_md(ln) for ln in lines if ln.lstrip().startswith("#")]
    paras: list[str] = []
    buf: list[str] = []
    for ln in lines + [""]:
        if not ln.strip() or ln.lstrip().startswith("#"):
            if buf:
                paras.append(" ".join(buf))
                buf = []
            continue
        if ln.lstrip()[:2] in {"- ", "* "}:
            continue
        buf.append(_strip_md(ln))
    first = next((p for p in paras if len(p) > 40), paras[0] if paras else "")
    brief = " ".join(_SENT_RE.split(first)[:2]).strip()
    if not brief:
        brief = "No readable prose in this document."
    points = [h for h in headings[1:6] if h] if len(headings) > 1 else []
    if not points:
        points = [" ".join(_SENT_RE.split(p)[:1])[:160] for p in paras[1:4]]
    return brief[:500], [p for p in points if p][:5]


def brief(state: SummarizerState) -> dict[str, Any]:
    use_llm = harness_env_available()
    out: list[dict[str, Any]] = []
    for d in state.get("documents") or []:
        d = dict(d)
        text = d.get("text") or ""
        if not text:
            d.update(brief=f"{d['name']}: {d.get('note') or 'no readable text'}.", key_points=[])
        else:
            parsed = None
            if use_llm:
                parsed = parse_json_object(
                    chat_completion(SYSTEM_PROMPT, f"{BRIEF_INSTRUCTIONS}\n\nFile: {d['path']}\n\n{text[:12000]}")
                )
            if parsed and parsed.get("brief"):
                d["brief"] = str(parsed["brief"]).strip()
                d["key_points"] = [str(p).strip() for p in (parsed.get("key_points") or []) if str(p).strip()][:5]
                d["brief_source"] = "llm"
            else:
                d["brief"], d["key_points"] = heuristic_brief(text)
                d["brief_source"] = "heuristic"
        d.pop("text", None)  # keep checkpoints small; text never needed again
        out.append(d)
    n_llm = sum(1 for d in out if d.get("brief_source") == "llm")
    note = "" if n_llm == len([d for d in out if d.get("brief_source")]) else (last_error() or "unknown")
    line = f"brief: {len(out)} docs, llm {n_llm}" + (f", fallback: {note}" if note else "")
    return {"documents": out, "llm_note": note, "stage_summaries": _append(state, line)}


# ---------------------------------------------------------------------------
# links
# ---------------------------------------------------------------------------


def links(state: SummarizerState) -> dict[str, Any]:
    docs = [dict(d) for d in state.get("documents") or []]
    note = ""
    folder_url = state.get("folder_url") or ""
    mode = state.get("source_mode")
    folder_id = state.get("folder_id") or ""

    if mode in {"fixture", "mount"} and folder_id and box_api.box_api_configured():
        try:
            items = {i.path: i for i in box_api.get_box_client().list_files(folder_id)}
            for d in docs:
                hit = items.get(d["path"])
                if hit:
                    d["file_id"], d["url"] = hit.id, hit.url
        except Exception as exc:  # noqa: BLE001
            note = f"Box link lookup failed ({str(exc)[:120]}); using folder links."

    access = os.environ.get("BOX_SHARED_LINK_ACCESS", "").strip()
    if access and mode in {"api", "mount"} and box_api.box_api_configured():
        client = box_api.get_box_client()
        for d in docs:
            if d.get("file_id") and "app.box.com/file/" in (d.get("url") or ""):
                try:
                    url = client.ensure_shared_link(d["file_id"], access)
                    if url:
                        d["url"] = url
                except Exception:  # noqa: BLE001
                    note = note or "Some shared links could not be created; using app.box.com file links."

    missing = 0
    for d in docs:
        if not d.get("url"):
            missing += 1
            if mode == "fixture" and not folder_id:
                d["url"] = (Path(state["local_root"]) / d["path"]).resolve().as_uri()
            else:
                d["url"] = folder_url
    if missing and not note and not (mode == "fixture" and not folder_id):
        note = f"{missing} file link(s) point at the folder because Box file ids were not available."
    return {"documents": docs, "links_note": note, "stage_summaries": _append(state, "links: done")}


# ---------------------------------------------------------------------------
# synthesize
# ---------------------------------------------------------------------------

_STOP = set(
    "the a an and or of to in on for with is are be by at as it this that from your you our we can will "
    "into each per more most best also over than about when what which while who where there their they "
    "its it's not but all any one two have has was were these those".split()
)


def _heuristic_themes(docs: list[dict[str, Any]]) -> list[str]:
    counts: Counter[str] = Counter()
    for d in docs:
        words = set(re.findall(r"[A-Za-z][A-Za-z'-]{3,}", f"{d.get('brief', '')} {' '.join(d.get('key_points') or [])}"))
        counts.update(w.lower() for w in words if w.lower() not in _STOP)
    common = [w for w, n in counts.most_common(12) if n > 1][:6]
    return [f"{w.capitalize()} comes up across multiple documents." for w in common]


def synthesize(state: SummarizerState) -> dict[str, Any]:
    docs = state.get("documents") or []
    folder_name = state.get("folder_name") or "Box folder"
    folder_url = state.get("folder_url") or ""
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    tldr, themes = "", []
    if harness_env_available():
        joined = "\n\n".join(
            f"[{d['path']}] {d.get('brief', '')}\n" + "\n".join(f"- {p}" for p in d.get("key_points") or [])
            for d in docs
        )
        parsed = parse_json_object(chat_completion(SYSTEM_PROMPT, f"{SYNTH_INSTRUCTIONS}\n\n{joined[:24000]}", max_tokens=3000))
        if parsed:
            tldr = str(parsed.get("tldr") or "").strip()
            themes = [str(t).strip() for t in parsed.get("themes") or [] if str(t).strip()][:6]
    if not tldr:
        prose = [
            d for d in docs
            if d.get("brief") and d.get("supported") and d["name"].lower().rsplit(".", 1)[-1] in {"md", "txt", "docx", "pdf", "pptx", "markdown"}
        ]
        lead = [_SENT_RE.split(d["brief"])[0].rstrip(".") for d in prose[:4]]
        tldr = f"{len(docs)} document{'s' if len(docs) != 1 else ''} in {folder_name}."
        if lead:
            tldr += " Highlights: " + "; ".join(lead) + "."
    llm_synth = bool(themes)
    synth_note = "" if llm_synth else (last_error() or "no LLM")

    lines = [
        f"# Executive Summary: {folder_name}",
        "",
        f"Folder: [{folder_name}]({folder_url})  ",
        f"Generated: {generated}  ",
        f"Documents: {len(docs)}",
        "",
        "## TL;DR",
        "",
        tldr,
        "",
    ]
    if themes:
        lines += ["## Themes", ""] + [f"- {t}" for t in themes] + [""]
    lines += ["## Documents", ""]
    for d in docs:
        lines.append(f"### [{d['path']}]({d['url']})")
        lines.append("")
        lines.append(d.get("brief") or "")
        kp = d.get("key_points") or []
        if kp:
            lines.append("")
            lines += [f"- {p}" for p in kp]
        lines.append("")
    lines += ["## Sources", ""] + [f"- [{d['path']}]({d['url']})" for d in docs] + [""]
    skipped = state.get("skipped") or []
    if skipped:
        lines += ["## Skipped", ""] + [f"- {s['path']}: {s['reason']}" for s in skipped] + [""]
    if state.get("links_note"):
        lines += [f"_Note: {state['links_note']}_", ""]
    fallback = state.get("llm_note") or synth_note
    if fallback:
        lines += [f"_Note: model unavailable ({fallback}); briefs are extractive._", ""]
    lines.append("_Generated by Box Doc Summarizer on DigitalOcean Managed Agents._")
    md = hygiene_text("\n".join(lines))
    line = "synthesize: llm" if llm_synth else f"synthesize: heuristic ({synth_note})"
    out = {"summary_md": md, "stage_summaries": _append(state, line)}
    if synth_note and not state.get("llm_note"):
        out["llm_note"] = synth_note
    return out


# ---------------------------------------------------------------------------
# ask / write_back / report
# ---------------------------------------------------------------------------


def ask(state: SummarizerState) -> dict[str, Any]:
    if state.get("auto_approve"):
        return {"decision": "approve", "stage_summaries": _append(state, "ask: auto-approve")}
    from langgraph.types import interrupt

    md = state.get("summary_md") or ""
    preview = md if len(md) <= 3000 else md[:3000].rsplit("\n", 1)[0] + "\n…"
    payload = {
        "title": ask_title(),
        "body": ask_body(
            folder_name=state.get("folder_name") or "the folder",
            filename=summary_filename(),
            doc_count=len(state.get("documents") or []),
            preview=preview,
        ),
        "choices": ["approve", "deny"],
        "pending_action": "write_summary",
    }
    decision = _normalize_decision(interrupt(payload))
    return {"ask_payload": payload, "decision": decision, "stage_summaries": _append(state, f"ask: {decision}")}


def route_after_ask(state: SummarizerState) -> str:
    return "write_back" if state.get("decision") == "approve" else "report"


def _wait_mount_upload(folder_id: str, name: str, content: str) -> str:
    """Poll Box (read-only API) until the mount daemon has uploaded ``name`` with matching content."""
    if not folder_id or not box_api.box_api_configured():
        return ""
    deadline = time.time() + _int_env("BOX_MOUNT_UPLOAD_WAIT_S", 90)
    want = content.encode("utf-8")
    client = box_api.get_box_client()
    while time.time() < deadline:
        try:
            for item in client.list_files(folder_id, max_depth=1):
                if item.path == name and client.download(item.id) == want:
                    return item.url
        except Exception:  # noqa: BLE001
            pass
        time.sleep(3)
    return ""


def write_back(state: SummarizerState) -> dict[str, Any]:
    md = state.get("summary_md") or ""
    name = summary_filename()
    mode = state.get("source_mode")
    synced = False
    try:
        if mode == "api":
            item = box_api.get_box_client().upload_text(
                state["folder_id"], name, md, existing_file_id=state.get("existing_summary_id") or ""
            )
            return {
                "status": "written",
                "written_path": name,
                "written_url": item.url,
                "stage_summaries": _append(state, f"write_back: box file {item.id}"),
            }
        daemon_note = ""
        if mode == "mount":
            # The HITL interrupt ends the run; MARS may reap the sync daemon
            # before resume. Re-check and restart (box-mount mount restarts).
            res = box_mount.ensure_mount(state.get("folder_id") or "")
            if not res.ok:
                return {
                    "status": "write_failed",
                    "write_error": f"Box Mount not running at write time: {res.message}",
                    "stage_summaries": _append(state, "write_back: mount not running; nothing written"),
                }
            daemon_note = f"daemon {res.state}; "
        target_dir = Path(state.get("write_dir") or state.get("local_root") or ".")
        target = target_dir / name
        # In-place write (no temp+rename) so Box Mount keeps version history.
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(md)
        url = target.resolve().as_uri()
        note = f"write_back: {target}"
        if mode == "mount":
            url = state.get("folder_url") or url
            note = f"write_back: {daemon_note}wrote {target} via mount"
            synced = _wait_mount_upload(state.get("folder_id") or "", name, md)
            if synced:
                url = synced
                note += f"; synced to Box ({synced})"
            else:
                note += "; Box sync NOT confirmed before timeout"
        return {
            "mount_synced": bool(mode == "mount" and synced),
            "status": "written",
            "written_path": str(target),
            "written_url": url,
            "stage_summaries": _append(state, note),
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "write_failed", "write_error": str(exc)[:200], "stage_summaries": _append(state, "write_back: failed")}


def report(state: SummarizerState) -> dict[str, Any]:
    status = state.get("status") or ""
    md = state.get("summary_md") or ""
    if status == "blocked":
        text = blocked_message(state.get("blocked_reason") or "unknown error")
    elif status == "empty":
        text = empty_message(state.get("folder_name") or "That folder")
    elif status == "written" and state.get("source_mode") == "mount" and not state.get("mount_synced"):
        text = f"I wrote {summary_filename()} into the mounted folder, but Box hasn't confirmed the upload yet. Check the folder in a minute: {state.get('folder_url') or ''}\n\n" + md
    elif status == "written":
        text = written_message(summary_filename(), state.get("written_url") or "") + md
    elif status == "write_failed":
        text = write_failed_message(state.get("write_error") or "unknown error") + md
    else:
        status = "denied" if state.get("decision") == "deny" else "summarized"
        text = (denied_message() if status == "denied" else "") + md
    mode = state.get("source_mode") or ""
    if mode and status not in {"chat", "help"} and state.get("intent") == "summarize":
        footer = f"Run mode: {mode}"
        if mode == "mount":
            steps = "; ".join(state.get("mount_steps") or [])
            footer += f" ({state.get('mount_state') or ''}{': ' + steps if steps else ''})"
        if status == "written" and mode == "mount":
            footer += ". Summary written through the mount" + (
                ", upload to Box confirmed." if state.get("mount_synced") else ", but the upload to Box was not confirmed yet."
            )
        text = text.rstrip() + "\n\n" + footer
    return {
        "status": status,
        "human_summary": text,
        **_CLEAR,
        "stage_summaries": _append(state, f"report: complete (source_mode={mode or 'n/a'})"),
        **_reply(text),
    }


intake_node = _mars_node(intake)
connect_node = _mars_node(connect)
inventory_node = _mars_node(inventory)
extract_node = _mars_node(extract)
brief_node = _mars_node(brief)
links_node = _mars_node(links)
synthesize_node = _mars_node(synthesize)
ask_node = _mars_node(ask)
write_back_node = _mars_node(write_back)
report_node = _mars_node(report)
list_files_node = _mars_node(list_files)
