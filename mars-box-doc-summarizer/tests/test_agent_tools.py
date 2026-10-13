"""LLM tool-calling intake with a mocked model (no network)."""

import json
import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from box_doc_summarizer import agent, box_api, nodes
from box_doc_summarizer.graph import compile_graph
from box_doc_summarizer.intent import classify_intent
from helpers import FIXTURE, FakeBoxClient
from test_list_and_resolve import FOLDERS


def call(name, **args):
    return {"content": "", "tool_calls": [{"id": f"c-{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def say(text):
    return {"content": text}


class Script:
    """Scripted model: pops one assistant message per call and records the prompts."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.seen = []

    def __call__(self, messages, tools, **kw):
        self.seen.append(messages)
        assert {t["function"]["name"] for t in tools} == {"list_folders", "list_files", "summarize_folder"}
        return self.turns.pop(0)


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "test-key")
    monkeypatch.setattr(nodes, "chat_completion", lambda *a, **k: None)  # briefs/synthesis use heuristics

    def install(*turns):
        s = Script(*turns)
        monkeypatch.setattr(agent, "chat_with_tools", s)
        return s

    return install


def _ai(out):
    return [m for m in out["messages"] if isinstance(m, AIMessage)][-1].content


def test_list_folders_with_folder_id_preset_never_summarizes(llm, monkeypatch):
    monkeypatch.setenv("BOX_FOLDER_ID", "111")
    fake = FakeBoxClient(folders=FOLDERS)
    box_api.set_box_client_factory(lambda: fake)
    s = llm(call("list_folders"), say("I can see box-doc-summarizer-test and Finance/Reports."))
    out = compile_graph().invoke({"messages": [HumanMessage(content="list folders")], "folder_id": "111"})
    assert "__interrupt__" not in out and not out.get("summary_md")
    assert out["status"] == "chat" and "box-doc-summarizer-test" in _ai(out)
    assert fake.uploads == [] and "Run mode" not in _ai(out)
    tool_msg = s.seen[1][-1]
    assert tool_msg["role"] == "tool" and '"id": "222"' in tool_msg["content"]


def test_list_folders_after_summary_on_same_thread_does_not_resummarize(llm, tmp_path):
    """The real bug: a checkpointed folder_id from an earlier summary forced the next turn to summarize."""
    g = compile_graph(MemorySaver())
    cfg = {"configurable": {"thread_id": uuid.uuid4().hex}}
    box_api.set_box_client_factory(lambda: FakeBoxClient(folders=FOLDERS))
    llm(call("summarize_folder"), call("list_folders"), say("Here are your folders: box-doc-summarizer-test, Finance/Reports."))
    first = g.invoke({"messages": [HumanMessage(content="summarize it")], "fixture_path": str(FIXTURE), "write_dir": str(tmp_path)}, cfg)
    assert first.get("__interrupt__")
    g.invoke(Command(resume="approve"), cfg)
    written = (tmp_path / "EXECUTIVE-SUMMARY.md").stat().st_mtime_ns
    assert g.get_state(cfg).values.get("folder_id") == "" and g.get_state(cfg).values.get("fixture_path") == ""
    out = g.invoke({"messages": [HumanMessage(content="list folders")]}, cfg)
    assert "__interrupt__" not in out and out["status"] == "chat"
    assert (tmp_path / "EXECUTIVE-SUMMARY.md").stat().st_mtime_ns == written


def test_chat_reply_uses_history(llm):
    s = llm(say("Hey! I list folders, peek inside them, and draft exec summaries you approve."))
    msgs = [HumanMessage(content="hi"), AIMessage(content="Hi there"), HumanMessage(content="hey what can you do?")]
    out = compile_graph().invoke({"messages": msgs})
    assert out["status"] == "chat" and "exec summaries" in _ai(out)
    roles = [m["role"] for m in s.seen[0]]
    assert roles == ["system", "user", "assistant", "user"]


def test_list_files_by_name_resolves_via_tool(llm, tmp_path, monkeypatch):
    from tests_box_mount_fake import install_fake_mount

    install_fake_mount(tmp_path, monkeypatch)
    box_api.set_box_client_factory(lambda: FakeBoxClient(folders=FOLDERS))
    llm(call("list_files", folder="box-doc-summarizer-test"))
    out = compile_graph().invoke({"messages": [HumanMessage(content="what's in the test folder?")]})
    assert out["status"] == "listed" and "q3-roadmap.md" in _ai(out) and not out.get("summary_md")


def test_summarize_tool_goes_through_hitl(llm):
    fake = FakeBoxClient(folders=FOLDERS)
    box_api.set_box_client_factory(lambda: fake)
    import os

    os.environ["BOX_ALLOW_API_FALLBACK"] = "1"
    try:
        llm(call("summarize_folder", folder="111"))
        g = compile_graph(MemorySaver())
        cfg = {"configurable": {"thread_id": uuid.uuid4().hex}}
        out = g.invoke({"messages": [HumanMessage(content="exec summary of it please")]}, cfg)
        assert out.get("__interrupt__") and fake.uploads == []
        out = g.invoke(Command(resume="approve"), cfg)
        assert fake.uploads and "Run mode: api" in _ai(out)
    finally:
        os.environ.pop("BOX_ALLOW_API_FALLBACK", None)


def test_summarize_without_folder_uses_default_only_then(llm, monkeypatch, tmp_path):
    monkeypatch.setenv("BOX_FOLDER_ID", "111")
    s = llm(call("summarize_folder"))
    out = compile_graph(MemorySaver()).invoke(
        {"messages": [HumanMessage(content="summarize")], "fixture_path": str(FIXTURE)},
        {"configurable": {"thread_id": "t"}},
    )
    assert out.get("__interrupt__")
    assert "Default folder id" in s.seen[0][0]["content"]


def test_unresolved_name_is_conversational(llm):
    box_api.set_box_client_factory(lambda: FakeBoxClient(folders=FOLDERS))
    llm(call("summarize_folder", folder="Reports"))
    out = compile_graph().invoke({"messages": [HumanMessage(content="summarize Reports")]})
    assert out["status"] == "chat" and "Which one" in _ai(out)


def test_llm_down_falls_back_to_regex_and_never_summarizes_lists(llm, monkeypatch):
    monkeypatch.setenv("BOX_FOLDER_ID", "111")
    llm(None)
    box_api.set_box_client_factory(lambda: FakeBoxClient(folders=FOLDERS))
    out = compile_graph().invoke({"messages": [HumanMessage(content="list folders")], "folder_id": "111"})
    assert out["status"] == "listed" and not out.get("summary_md")


@pytest.mark.parametrize("text", ["show me the exec summary", "list the summary", "what's in the summary folder"])
def test_regex_list_show_never_summarize(text):
    assert classify_intent(text) != "summarize"
