"""Default offline inference keys so ambient box env cannot hit live HTTP."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_inference_keys(monkeypatch):
    """Clear harness/OpenAI keys unless a test sets them via monkeypatch."""
    monkeypatch.delenv("HARNESS_INFERENCE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
