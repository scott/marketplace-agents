"""LangGraph wrapper for Managed Agents (MARS / Open Harness) deployment.

MARS serves a compiled graph via the official LangGraph Agent Server.
This module is a thin adapter around the existing LangChain Agent — it does
not rewrite the writing or publishing logic.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

logger = logging.getLogger("ghost-writer")

PUBLISH_SENTINEL = "__GW_PUBLISH__"

_agent = None


class GraphState(TypedDict):
    messages: Annotated[list, add_messages]


def apply_harness_inference_env() -> None:
    """Map HARNESS_INFERENCE_* (then OPENAI_*) onto Gradient vars Agent reads."""
    if not os.getenv("GRADIENT_MODEL_ACCESS_KEY"):
        harness_key = (
            os.getenv("HARNESS_INFERENCE_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
        if harness_key:
            os.environ["GRADIENT_MODEL_ACCESS_KEY"] = harness_key

    if not os.getenv("GRADIENT_MODEL"):
        harness_model = (
            os.getenv("HARNESS_INFERENCE_MODEL")
            or os.getenv("OPENAI_MODEL")
            or ""
        )
        if harness_model:
            os.environ["GRADIENT_MODEL"] = harness_model

    if not os.getenv("GRADIENT_BASE_URL"):
        harness_base = (
            os.getenv("HARNESS_INFERENCE_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or ""
        )
        if harness_base:
            os.environ["GRADIENT_BASE_URL"] = harness_base.rstrip("/") + "/"


def _message_text(message: BaseMessage | dict) -> str:
    content = (
        message.get("content")
        if isinstance(message, dict)
        else getattr(message, "content", "")
    )
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content or "")


def _is_human(message: BaseMessage | dict) -> bool:
    if isinstance(message, dict):
        return message.get("type") == "human" or message.get("role") == "user"
    return isinstance(message, HumanMessage) or getattr(message, "type", None) == "human"


def last_user_text(state: GraphState) -> str:
    for message in reversed(state.get("messages") or []):
        if _is_human(message):
            return _message_text(message).strip()
    return ""


def should_publish(text: str) -> bool:
    if os.getenv("GW_RUN_MODE", "").strip().lower() == "publish":
        return True
    return text == PUBLISH_SENTINEL


def _get_agent():
    global _agent
    if _agent is None:
        apply_harness_inference_env()
        from ghost_writer.agent import Agent

        _agent = Agent()
    return _agent


def run(state: GraphState) -> dict:
    text = last_user_text(state)
    agent = _get_agent()

    if should_publish(text):
        logger.info("MARS graph: autonomous publish")
        response = agent.generate_and_publish()
    else:
        logger.info("MARS graph: chat")
        response = agent.process_message(text)

    return {"messages": [AIMessage(content=response)]}


def build_graph():
    builder = StateGraph(GraphState)
    builder.add_node("ghost_writer", run)
    builder.set_entry_point("ghost_writer")
    builder.add_edge("ghost_writer", END)
    return builder.compile()


graph = build_graph()
