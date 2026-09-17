"""Compiled Competitor Pulse graph (MARS / LangGraph Agent Server export)."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from competitor_pulse.nodes import (
    act,
    ask,
    execute_pulse,
    intake_node,
    report,
    route_after_intake,
    should_ask,
)
from competitor_pulse.state import InputState, OutputState, PulseState


def build_graph() -> StateGraph:
    """Construct the uncompiled StateGraph.

    Chat/help/other: ``intake`` emits a single ``AIMessage`` and routes to END
    (diag-shaped one-node reply — avoids stream+converse duplication on MARS).

    Pulse: ``intake`` → ``execute_pulse`` → optional ask/act → ``report`` → END.
    Competitor lists live under ``internal.competitors`` (not in input/output
    schemas). Fixture files are ``competitors*.json`` (no ``watchlist`` names).
    """
    builder: StateGraph = StateGraph(
        PulseState,
        input_schema=InputState,
        output_schema=OutputState,
    )
    builder.add_node("intake", intake_node)
    builder.add_node("execute_pulse", execute_pulse)
    builder.add_node("ask", ask)
    builder.add_node("act", act)
    builder.add_node("report", report)

    builder.add_edge(START, "intake")
    builder.add_conditional_edges(
        "intake",
        route_after_intake,
        {"end": END, "execute_pulse": "execute_pulse", "report": "report"},
    )
    builder.add_conditional_edges(
        "execute_pulse",
        should_ask,
        {"ask": "ask", "report": "report"},
    )
    builder.add_edge("ask", "act")
    builder.add_edge("act", "report")
    builder.add_edge("report", END)
    return builder


def compile_graph(checkpointer: Any = None):
    """Compile with optional checkpointer (required for interrupt resume locally)."""
    builder = build_graph()
    kwargs: dict[str, Any] = {"name": "Competitor Pulse"}
    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer
    return builder.compile(**kwargs)


# Module-level compiled export for langgraph.json / Agent Server
graph = compile_graph()
