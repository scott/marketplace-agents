"""Compiled Box Doc Summarizer graph (MARS / LangGraph Agent Server export)."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from box_doc_summarizer.nodes import (
    ask_node,
    brief_node,
    connect_node,
    extract_node,
    intake_node,
    inventory_node,
    links_node,
    list_files_node,
    report_node,
    route_after_ask,
    route_after_connect,
    route_after_intake,
    route_after_inventory,
    synthesize_node,
    write_back_node,
)
from box_doc_summarizer.state import InputState, OutputState, SummarizerState


def build_graph() -> StateGraph:
    b: StateGraph = StateGraph(SummarizerState, input_schema=InputState, output_schema=OutputState)
    for name, fn in [
        ("intake", intake_node),
        ("connect", connect_node),
        ("inventory", inventory_node),
        ("extract", extract_node),
        ("brief", brief_node),
        ("links", links_node),
        ("synthesize", synthesize_node),
        ("ask", ask_node),
        ("write_back", write_back_node),
        ("report", report_node),
        ("list_files", list_files_node),
    ]:
        b.add_node(name, fn)
    b.add_edge(START, "intake")
    b.add_conditional_edges("intake", route_after_intake, {"end": END, "connect": "connect"})
    b.add_conditional_edges("connect", route_after_connect, {"report": "report", "inventory": "inventory", "list_files": "list_files"})
    b.add_conditional_edges("inventory", route_after_inventory, {"report": "report", "extract": "extract"})
    b.add_edge("extract", "brief")
    b.add_edge("brief", "links")
    b.add_edge("links", "synthesize")
    b.add_edge("synthesize", "ask")
    b.add_conditional_edges("ask", route_after_ask, {"write_back": "write_back", "report": "report"})
    b.add_edge("write_back", "report")
    b.add_edge("report", END)
    b.add_edge("list_files", END)
    return b


def compile_graph(checkpointer: Any = None):
    kwargs: dict[str, Any] = {"name": "BoxDocSummarizer"}
    if checkpointer is not None:
        kwargs["checkpointer"] = checkpointer
    return build_graph().compile(**kwargs)


graph = compile_graph()
