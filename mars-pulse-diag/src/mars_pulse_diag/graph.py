"""Minimal diagnostic graph: messages-only state, fixed AIMessage reply.

Used to prove whether MARS/doctl injects {"watchlist":[]} into prompt text
independent of Competitor Pulse graph state/schemas.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, START, StateGraph, add_messages


class State(TypedDict):
    """State with ONLY messages — no watchlist / competitors / structured fields."""

    messages: Annotated[list[BaseMessage], add_messages]


def diag_reply(state: State) -> dict:
    """Single node: return the exact diagnostic marker string."""
    return {
        "messages": [
            AIMessage(content="DIAG_OK no-structured-state"),
        ]
    }


def build_graph() -> StateGraph:
    builder: StateGraph = StateGraph(State)
    builder.add_node("diag", diag_reply)
    builder.add_edge(START, "diag")
    builder.add_edge("diag", END)
    return builder


def compile_graph():
    return build_graph().compile(name="mars-pulse-diag")


# Module-level compiled export for langgraph.json / Agent Server
graph = compile_graph()
