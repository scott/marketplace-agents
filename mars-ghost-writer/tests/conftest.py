"""Shared fixtures for ghost-writer tests."""

from __future__ import annotations

import os
import types
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove blog / gradient env vars so tests start from a clean slate."""
    for var in (
        "BLOG_TYPE",
        "BLOG_URL",
        "BLOG_API_KEY",
        "GRADIENT_MODEL_ACCESS_KEY",
        "GRADIENT_MODEL",
        "GRADIENT_BASE_URL",
        "BLOG_TOPIC",
        "ENABLE_CHAT",
        "BLOGS_PER_DAY",
        "HARNESS_INFERENCE_API_KEY",
        "HARNESS_INFERENCE_MODEL",
        "HARNESS_INFERENCE_BASE_URL",
        "OPENAI_API_KEY",
        "OPENAI_MODEL",
        "OPENAI_BASE_URL",
        "GW_RUN_MODE",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def blog_env(monkeypatch):
    """Set standard blog env vars for tests that need them."""
    monkeypatch.setenv("BLOG_TYPE", "ghost")
    monkeypatch.setenv("BLOG_URL", "https://example.com")
    monkeypatch.setenv("BLOG_API_KEY", "abc123:aabbccdd")
    monkeypatch.setenv("GRADIENT_MODEL_ACCESS_KEY", "test-key")


@pytest.fixture(autouse=True)
def _reset_draft_store():
    """Clear the draft store between tests."""
    from ghost_writer.tools import _draft_store

    _draft_store.clear()
    yield
    _draft_store.clear()


@pytest.fixture()
def mock_agent():
    """Build an Agent with LLM / executors / blog load stubbed out."""
    from ghost_writer.agent import Agent as _RealAgent

    _real_load = _RealAgent._load_recent_titles

    with patch.dict(
        os.environ,
        {
            "GRADIENT_MODEL_ACCESS_KEY": "test-key",
            "BLOG_TOPIC": "Technology",
        },
    ):
        with patch("ghost_writer.agent.ChatOpenAI") as mock_llm_cls, patch(
            "ghost_writer.agent.create_tool_calling_agent"
        ), patch("ghost_writer.agent.AgentExecutor") as mock_exec_cls, patch(
            "ghost_writer.agent.Agent._load_recent_titles"
        ):
            mock_llm = MagicMock()
            mock_llm_cls.return_value = mock_llm

            mock_chat_exec = MagicMock()
            mock_write_exec = MagicMock()
            mock_exec_cls.side_effect = [mock_chat_exec, mock_write_exec]

            agent = _RealAgent()
            agent.llm = mock_llm
            agent.chat_executor = mock_chat_exec
            agent.write_executor = mock_write_exec
            agent._load_recent_titles = types.MethodType(_real_load, agent)

            yield agent
