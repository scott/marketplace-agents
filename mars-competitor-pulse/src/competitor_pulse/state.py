"""Graph state for Competitor Pulse."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class WatchItem(TypedDict, total=False):
    name: str
    urls: dict[str, str]


class InternalState(TypedDict, total=False):
    """Graph-internal payload — never in input/output schemas or MARS stream text."""

    competitors: list[dict[str, Any]]
    pending_track: dict[str, Any]


class InputState(TypedDict, total=False):
    """MARS / doctl chat input — no competitors (avoids empty list-field echo in doctl text)."""

    messages: Annotated[list[AnyMessage], add_messages]
    user_message: str
    allow_net: bool
    notify: bool
    channel: str
    fixture_dir: str
    baseline_path: str
    snapshot_dir: str
    force_empty: bool
    force_material: bool
    force_blocked: bool
    pending_track: dict[str, Any]


class OutputState(TypedDict, total=False):
    """Agent Server / doctl-visible output — chat text lives in ``messages`` only."""

    messages: Annotated[list[AnyMessage], add_messages]
    status: str
    material: bool
    first_run: bool
    brief_md: str
    next_hint: str
    artifacts: list[str]
    delta_count: int
    skipped: bool
    notified: bool
    notify_id: str
    decision: str


class PulseState(TypedDict, total=False):
    # MARS chat passes messages; intake parses JSON from HumanMessage
    messages: Annotated[list[AnyMessage], add_messages]

    # Chat / intake (tests and legacy invoke)
    user_message: str
    chat_ack: str
    intent: str  # chat | help | track_plan | pulse | other

    # Internal graph payload (not in InputState / OutputState / doctl text)
    internal: InternalState
    pending_track: dict[str, Any]
    watch_names: list[str]  # MARS-safe names (no raw watchlist JSON in stream)
    blocked_reason: str
    notify: bool
    channel: str
    fixture_dir: str
    baseline_path: str
    snapshot_dir: str
    allow_net: bool
    force_empty: bool  # test: treat as non-material
    force_material: bool  # test helper (unused if baseline diverges)
    force_blocked: bool

    # Plan
    modules: list[str]
    run_id: str

    # Gather
    snapshots: list[dict[str, Any]]

    # Analyze
    deltas: list[dict[str, Any]]
    baseline_captures: list[dict[str, Any]]
    first_run: bool
    material: bool

    # Draft
    brief_md: str
    counterpositions: list[str]
    delta_count: int
    notify_draft: str

    # Ask / act
    pending_action: str
    ask_payload: dict[str, Any]
    decision: str  # approve | deny
    notified: bool
    notify_id: str
    skipped: bool
    baseline_updated: bool

    # Report
    status: str  # empty | notified | denied | blocked | error | ok | baseline
    human_summary: str  # run artifacts / smoke — not streamed for doctl ``text``
    stage_summaries: list[str]
    artifacts: list[str]
    next_hint: str
