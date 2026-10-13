#!/usr/bin/env python3
"""Offline smoke for Box Doc Summarizer (no API key, no network, no binary).

Exercises: chat hi, blocked (no Box creds), fixture deny, fixture approve
(write into a temp dir), and Box API mode approve with a mocked Box client.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

for k in ("HARNESS_INFERENCE_API_KEY", "OPENAI_API_KEY", "BOX_JWT_CONFIG_JSON", "BOX_MOUNT_BINARY_URL", "BOX_FOLDER_ID"):
    os.environ.pop(k, None)

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from box_doc_summarizer import box_api  # noqa: E402
from box_doc_summarizer.graph import compile_graph  # noqa: E402
from helpers import FIXTURE, FakeBoxClient  # noqa: E402


def _ask_then(payload, decision):
    g = compile_graph(MemorySaver())
    cfg = {"configurable": {"thread_id": uuid.uuid4().hex}}
    first = g.invoke(payload, cfg)
    if not first.get("__interrupt__"):
        raise SystemExit("SMOKE FAIL: expected ask interrupt")
    return g.invoke(Command(resume=decision), cfg)


def _check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        raise SystemExit(1)


def main() -> int:
    print("=== Box Doc Summarizer smoke (offline) ===")
    hi = compile_graph().invoke({"messages": [HumanMessage(content="hi")]})
    _check(sum(isinstance(m, AIMessage) for m in hi["messages"]) == 1, "hi emits one AIMessage")

    blocked = compile_graph().invoke({"messages": [HumanMessage(content="Summarize folder 123456789")]})
    _check(blocked["status"] == "blocked", "blocked without BOX_JWT_CONFIG_JSON")

    with tempfile.TemporaryDirectory() as tmp:
        denied = _ask_then({"fixture_path": str(FIXTURE), "write_dir": tmp}, "deny")
        _check(denied["status"] == "denied" and not (Path(tmp) / "EXECUTIVE-SUMMARY.md").exists(), "fixture deny writes nothing")

        folder = Path(tmp) / "folder"
        shutil.copytree(FIXTURE, folder)
        approved = _ask_then({"fixture_path": str(folder)}, "approve")
        out = folder / "EXECUTIVE-SUMMARY.md"
        _check(approved["status"] == "written" and out.exists(), f"fixture approve wrote {out.name}")

    fake = FakeBoxClient()
    box_api.set_box_client_factory(lambda: fake)
    api = _ask_then({"messages": [HumanMessage(content="Summarize https://app.box.com/folder/111")]}, "approve")
    md = api["summary_md"]
    links_ok = all(f"]({d['url']})" in md and d["url"].startswith("https://app.box.com/file/") for d in api["documents"])
    _check(api["status"] == "written" and len(fake.uploads) == 1, "api approve uploaded summary via mocked Box client")
    _check(links_ok, f"per-file Box links present for {len(api['documents'])} docs")
    box_api.set_box_client_factory(None)

    print("\n--- summary preview ---")
    print("\n".join(md.splitlines()[:14]))
    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
