import pytest
from langchain_core.messages import AIMessage, HumanMessage

from box_doc_summarizer import box_api
from box_doc_summarizer.graph import compile_graph
from box_doc_summarizer.intent import classify_intent, parse_folder_id, parse_folder_name
from box_doc_summarizer.nodes import resolve_folder_name
from helpers import FakeBoxClient
from tests_box_mount_fake import install_fake_mount


@pytest.mark.parametrize(
    "text,intent",
    [
        ("list folders", "list_folders"),
        ("What folders can you see?", "list_folders"),
        ("show me my folders", "list_folders"),
        ("list files", "list_files"),
        ("list files in box-doc-summarizer-test", "list_files"),
        ("what's in 426859578396", "list_files"),
        ("What’s in Hawaii Trip?", "list_files"),
        ("show files in folder 426859578396", "list_files"),
        ("list files 426859578396", "list_files"),
        ("summarize box-doc-summarizer-test", "summarize"),
        ("Summarize folder 426859578396", "summarize"),
        ("426859578396", "summarize"),
        ("refresh", "summarize"),
        ("help", "help"),
        ("hi", "chat"),
    ],
)
def test_intents(text, intent):
    assert classify_intent(text) == intent


def test_list_wins_over_numeric_id():
    t = "list files in folder 426859578396 and run"
    assert classify_intent(t) == "list_files" and parse_folder_id(t) == "426859578396"


def test_folder_name_parsing():
    assert parse_folder_name("summarize box-doc-summarizer-test") == "box-doc-summarizer-test"
    assert parse_folder_name("list files in 'Hawaii Trip'") == "Hawaii Trip"
    assert parse_folder_name("what's in Hawaii Trip?") == "Hawaii Trip"
    assert parse_folder_name("brief me on Q3 Plans") == "Q3 Plans"
    assert parse_folder_name("summarize folder 123456") == ""
    assert parse_folder_name("summarize my stuff") == ""
    assert parse_folder_name("list files") == ""


FOLDERS = [
    ("111", "box-doc-summarizer-test", "box-doc-summarizer-test"),
    ("222", "Reports", "Finance/Reports"),
    ("333", "Reports", "Sales/Reports"),
    ("444", "Hawaii Trip", "Hawaii Trip"),
]


def test_resolve_exact_case_insensitive():
    box_api.set_box_client_factory(lambda: FakeBoxClient(folders=FOLDERS))
    assert resolve_folder_name("BOX-DOC-SUMMARIZER-TEST") == ("111", "")
    assert resolve_folder_name("finance/reports") == ("222", "")


def test_resolve_ambiguous_lists_ids():
    box_api.set_box_client_factory(lambda: FakeBoxClient(folders=FOLDERS))
    fid, msg = resolve_folder_name("reports")
    assert fid == "" and "Which one" in msg and "id 222" in msg and "id 333" in msg


def test_resolve_none_suggests_close():
    box_api.set_box_client_factory(lambda: FakeBoxClient(folders=FOLDERS))
    fid, msg = resolve_folder_name("hawai trip")
    assert fid == "" and "Did you mean" in msg and "id 444" in msg
    fid, msg = resolve_folder_name("zzzz")
    assert fid == "" and "List folders" in msg


def _ai(out):
    return [m for m in out["messages"] if isinstance(m, AIMessage)][-1].content


def test_list_folders_is_read_only():
    fake = FakeBoxClient(folders=FOLDERS)
    box_api.set_box_client_factory(lambda: fake)
    out = compile_graph().invoke({"messages": [HumanMessage(content="list folders")]})
    text = _ai(out)
    assert out["status"] == "listed" and "shared with my Box service account" in text
    assert "Finance/Reports (id 222)" in text and fake.uploads == [] and "Run mode" not in text


def test_list_files_via_mount_no_summary(tmp_path, monkeypatch):
    mount_dir = install_fake_mount(tmp_path, monkeypatch)
    clients = []
    box_api.set_box_client_factory(lambda: clients.append(FakeBoxClient()) or clients[-1])
    out = compile_graph().invoke({"messages": [HumanMessage(content="list files in box-doc-summarizer-test")]})
    text = _ai(out)
    assert out["status"] == "listed" and "read through Box Mount" in text
    assert "q3-roadmap.md" in text and "Run mode" not in text and "Executive Summary" not in text
    assert not (mount_dir / "EXECUTIVE-SUMMARY.md").exists() and all(c.uploads == [] for c in clients)


def test_list_files_defaults_to_box_folder_id(tmp_path, monkeypatch):
    install_fake_mount(tmp_path, monkeypatch)
    monkeypatch.setenv("BOX_FOLDER_ID", "111")
    box_api.set_box_client_factory(lambda: FakeBoxClient())
    out = compile_graph().invoke({"messages": [HumanMessage(content="list files")]})
    assert out["status"] == "listed" and "board-update.pdf" in _ai(out)


def test_list_files_with_id_does_not_summarize(tmp_path, monkeypatch):
    install_fake_mount(tmp_path, monkeypatch)
    box_api.set_box_client_factory(lambda: FakeBoxClient())
    out = compile_graph().invoke({"messages": [HumanMessage(content="what's in 111111")]})
    assert out["status"] in {"listed", "blocked"} and "Executive Summary" not in _ai(out)


def test_list_files_blocked_when_mount_fails_without_flag(tmp_path, monkeypatch):
    install_fake_mount(tmp_path, monkeypatch, fail=True)
    fake = FakeBoxClient()
    box_api.set_box_client_factory(lambda: fake)
    out = compile_graph().invoke({"messages": [HumanMessage(content="list files in folder 111111")]})
    assert out["status"] == "blocked" and "Box Mount" in _ai(out)


def test_summarize_by_name_resolves(monkeypatch):
    fake = FakeBoxClient(folders=FOLDERS)
    box_api.set_box_client_factory(lambda: fake)
    out = compile_graph().invoke({"messages": [HumanMessage(content="summarize box-doc-summarizer-test")], "auto_approve": True})
    assert out["status"] == "written" and fake.uploads[0]["folder_id"] == "111"
    assert "Run mode: api" in _ai(out)


def test_summarize_ambiguous_name_asks():
    box_api.set_box_client_factory(lambda: FakeBoxClient(folders=FOLDERS))
    out = compile_graph().invoke({"messages": [HumanMessage(content="summarize Reports")]})
    assert "Which one" in _ai(out) and out.get("status") == "chat"
