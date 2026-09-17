#!/usr/bin/env python3
"""Smoke invoke for Ghost Writer — offline graph routing (ALLOW_NET=0)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("ALLOW_NET", "0")

from langchain_core.messages import HumanMessage  # noqa: E402

from ghost_writer.graph import (  # noqa: E402
    PUBLISH_SENTINEL,
    apply_harness_inference_env,
    graph,
    last_user_text,
    should_publish,
)


def main() -> int:
    print("=== Ghost Writer smoke ===")
    print("ALLOW_NET:", os.environ.get("ALLOW_NET", "0"))

    assert should_publish(PUBLISH_SENTINEL)
    assert not should_publish("Write about cloud")
    assert last_user_text({"messages": [HumanMessage(content="hello")]}) == "hello"

    os.environ.pop("GRADIENT_MODEL_ACCESS_KEY", None)
    os.environ["HARNESS_INFERENCE_API_KEY"] = "smoke-key"
    os.environ["HARNESS_INFERENCE_MODEL"] = "deepseek-v4-pro"
    apply_harness_inference_env()
    assert os.environ["GRADIENT_MODEL_ACCESS_KEY"] == "smoke-key"

    mock_agent = MagicMock()
    mock_agent.process_message.return_value = "Draft ready — would you like me to publish?"
    with patch("ghost_writer.graph._get_agent", return_value=mock_agent):
        result = graph.invoke({"messages": [HumanMessage(content="Write about MARS agents")]})

    text = result["messages"][-1].content
    print("assistant:", text[:120], "..." if len(text) > 120 else "")
    mock_agent.process_message.assert_called_once_with("Write about MARS agents")

    print("\nSMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
