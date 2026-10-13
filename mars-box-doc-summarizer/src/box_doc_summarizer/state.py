"""Graph state for Box Doc Summarizer."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class InputState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    folder_id: str
    fixture_path: str  # local folder; skips Box reads (offline tests / dev)
    write_dir: str  # fixture mode: where approve writes the summary (default fixture_path)
    auto_approve: bool  # trigger/webhook runs with permissions.default: allow


class OutputState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    status: str
    summary_md: str
    documents: list[dict[str, Any]]
    folder_url: str
    written_path: str
    written_url: str
    mount_state: str
    mount_steps: list[str]
    mount_synced: bool
    source_mode: str
    links_note: str
    llm_note: str
    decision: str
    stage_summaries: list[str]


class SummarizerState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]
    intent: str
    folder_id: str
    folder_name: str
    folder_url: str
    fixture_path: str
    write_dir: str
    auto_approve: bool
    source_mode: str  # api | mount | fixture
    mount_state: str
    mount_steps: list[str]
    mount_synced: bool
    local_root: str
    blocked_reason: str
    documents: list[dict[str, Any]]
    skipped: list[dict[str, Any]]
    existing_summary_id: str
    links_note: str
    llm_note: str
    summary_md: str
    ask_payload: dict[str, Any]
    decision: str
    written_path: str
    written_url: str
    write_error: str
    status: str
    human_summary: str
    stage_summaries: list[str]
