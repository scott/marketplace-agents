#!/usr/bin/env python3
"""Smoke invoke for Competitor Pulse.

Runs fixture watchlist + baselines offline (ALLOW_NET=0, no API key).
Exercises quiet skip and ask→deny with a checkpointer.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("ALLOW_NET", "0")

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from competitor_pulse.graph import compile_graph  # noqa: E402
from competitor_pulse.mars_text import last_assistant_text, prepare_programmatic_payload  # noqa: E402
from competitor_pulse.llm import harness_env_available, resolve_llm_env  # noqa: E402
from competitor_pulse.pulse_diff import (  # noqa: E402
    default_baseline_path,
    default_watchlist,
    quiet_baseline_path,
)


def main() -> int:
    print("=== Competitor Pulse smoke ===")
    print("Harness / OpenAI env resolution:")
    resolved = resolve_llm_env()
    print(
        json.dumps(
            {
                "base_url": resolved["base_url"],
                "model": resolved["model"],
                "api_key_set": bool(resolved["api_key"]),
                "prefer": "HARNESS_INFERENCE_* then OPENAI_*",
                "ALLOW_NET": os.environ.get("ALLOW_NET", "0"),
            },
            indent=2,
        )
    )
    if not harness_env_available():
        print(
            "\nNo HARNESS_INFERENCE_API_KEY / OPENAI_API_KEY — "
            "using fixtures (deterministic offline)."
        )

    quiet_bl = quiet_baseline_path()
    material_bl = default_baseline_path()
    if not quiet_bl.is_file() or not material_bl.is_file():
        print("SMOKE FAIL: missing baseline fixtures", file=sys.stderr)
        return 1
    if not default_watchlist():
        print("SMOKE FAIL: empty watchlist fixture", file=sys.stderr)
        return 1

    # 1) Quiet path — no interrupt
    g_quiet = compile_graph()
    quiet = g_quiet.invoke(
        prepare_programmatic_payload(
            {
                "watchlist": default_watchlist(),
                "notify": True,
                "baseline_path": str(quiet_bl),
                "allow_net": False,
            }
        )
    )
    print("\n--- quiet path ---")
    print("status:", quiet.get("status"))
    print("material:", quiet.get("material"))
    if quiet.get("status") != "empty" or "__interrupt__" in quiet:
        print("SMOKE FAIL: quiet path should skip ask", file=sys.stderr)
        return 1

    # 2) Material + notify → ask → deny
    g = compile_graph(checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "smoke-pulse"}}
    mid = g.invoke(
        prepare_programmatic_payload(
            {
                "watchlist": default_watchlist(),
                "notify": True,
                "channel": "slack",
                "baseline_path": str(material_bl),
                "allow_net": False,
            }
        ),
        cfg,
    )
    print("\n--- ask interrupt ---")
    if "__interrupt__" not in mid:
        print("SMOKE FAIL: expected ask interrupt on material deltas", file=sys.stderr)
        return 1
    payload = mid["__interrupt__"][0].value
    print("title:", payload.get("title"))
    print("choices:", payload.get("choices"))
    print("pending_action:", payload.get("pending_action"))
    if payload.get("choices") != ["approve", "deny"]:
        print("SMOKE FAIL: choices must be approve/deny", file=sys.stderr)
        return 1
    if payload.get("title") != "Notify about competitor changes?":
        print("SMOKE FAIL: bad ask title", file=sys.stderr)
        return 1
    if payload.get("pending_action") != "notify":
        print("SMOKE FAIL: pending_action must be notify", file=sys.stderr)
        return 1

    final = g.invoke(Command(resume="deny"), cfg)
    print("\n--- after deny ---")
    print("status:", final.get("status"))
    print("skipped:", final.get("skipped"))
    print("notified:", final.get("notified"))
    print("delta_count:", final.get("delta_count"))
    print("\n--- assistant text ---")
    print(last_assistant_text(final))

    if final.get("status") != "denied" or final.get("notified"):
        print("SMOKE FAIL: deny should yield denied + no notify", file=sys.stderr)
        return 1

    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
