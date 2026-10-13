import shutil
import uuid

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from box_doc_summarizer import box_api
from box_doc_summarizer.graph import compile_graph
from helpers import FIXTURE, FakeBoxClient
from tests_box_mount_fake import install_fake_mount  # noqa: F401  (helper module below)


def _run(payload, decision=None):
    g = compile_graph(MemorySaver())
    cfg = {"configurable": {"thread_id": uuid.uuid4().hex}}
    out = g.invoke(payload, cfg)
    interrupts = out.get("__interrupt__") if isinstance(out, dict) else None
    if decision is not None:
        assert interrupts, "expected ask interrupt"
        out = g.invoke(Command(resume=decision), cfg)
    return out, interrupts


def _last_ai(out):
    return [m for m in out["messages"] if isinstance(m, AIMessage)][-1].content


def test_hi_and_help_emit_single_message():
    for text in ("hi", "help"):
        out = compile_graph().invoke({"messages": [HumanMessage(content=text)]})
        ais = [m for m in out["messages"] if isinstance(m, AIMessage)]
        assert len(ais) == 1 and "Box" in ais[0].content and "—" not in ais[0].content


def test_missing_folder_asks_for_it():
    out = compile_graph().invoke({"messages": [HumanMessage(content="summarize my stuff")]})
    assert "Which Box folder" in _last_ai(out)


def test_blocked_without_box_credentials():
    out = compile_graph().invoke({"messages": [HumanMessage(content="Summarize folder 123456789")]})
    assert out["status"] == "blocked"
    assert "BOX_JWT_CONFIG_JSON" in _last_ai(out)
    assert "summary_md" not in out or not out["summary_md"]


def test_fixture_deny_leaves_folder_untouched(tmp_path):
    out, interrupts = _run({"fixture_path": str(FIXTURE), "write_dir": str(tmp_path)}, "deny")
    payload = interrupts[0].value
    assert payload["title"] == "Write executive summary to Box?"
    assert payload["choices"] == ["approve", "deny"] and payload["pending_action"] == "write_summary"
    assert out["status"] == "denied"
    assert not (tmp_path / "EXECUTIVE-SUMMARY.md").exists()
    paths = {d["path"] for d in out["documents"]}
    assert paths == {"board-update.pdf", "customer-feedback.txt", "metrics.csv", "notes/diagram.png", "notes/hiring-plan.docx", "q3-roadmap.md"}
    assert "left Box untouched" in _last_ai(out)


def test_fixture_approve_writes_in_place(tmp_path):
    folder = tmp_path / "f"
    shutil.copytree(FIXTURE, folder)
    out, _ = _run({"fixture_path": str(folder)}, {"approved": True})
    assert out["status"] == "written"
    written = (folder / "EXECUTIVE-SUMMARY.md").read_text()
    assert written.startswith("# Executive Summary")
    for d in out["documents"]:
        assert f"]({d['url']})" in written
    # summary is excluded on the next run
    out2, _ = _run({"fixture_path": str(folder)}, "deny")
    assert all(d["path"] != "EXECUTIVE-SUMMARY.md" for d in out2["documents"])


def test_api_mode_approve_uploads_and_links(monkeypatch):
    fake = FakeBoxClient(shared={"q3-roadmap.md": "https://app.box.com/s/public-roadmap"})
    box_api.set_box_client_factory(lambda: fake)
    out, _ = _run({"messages": [HumanMessage(content="Summarize https://app.box.com/folder/111")]}, "approve")
    assert out["status"] == "written" and out["source_mode"] == "api"
    md = out["summary_md"]
    assert "https://app.box.com/s/public-roadmap" in md
    for d in out["documents"]:
        assert d["url"].startswith("https://app.box.com/")
        assert f"]({d['url']})" in md
    assert len(fake.uploads) == 1 and fake.uploads[0]["folder_id"] == "111"
    assert fake.uploads[0]["existing_file_id"] == ""
    # second run versions the existing file
    out2, _ = _run({"folder_id": "111"}, "approve")
    assert fake.uploads[1]["existing_file_id"] == "77777"
    assert all(d["path"] != "EXECUTIVE-SUMMARY.md" for d in out2["documents"])


def test_api_mode_shared_link_creation(monkeypatch):
    fake = FakeBoxClient()
    box_api.set_box_client_factory(lambda: fake)
    monkeypatch.setenv("BOX_SHARED_LINK_ACCESS", "open")
    out, _ = _run({"folder_id": "111"}, "deny")
    assert all(d["url"].startswith("https://app.box.com/s/fake") for d in out["documents"])
    assert fake.uploads == []


def test_auto_approve_skips_interrupt():
    fake = FakeBoxClient()
    box_api.set_box_client_factory(lambda: fake)
    out = compile_graph().invoke({"folder_id": "111", "auto_approve": True})
    assert out["status"] == "written" and len(fake.uploads) == 1


def test_mount_mode_end_to_end(tmp_path, monkeypatch):
    mount_dir = install_fake_mount(tmp_path, monkeypatch)
    monkeypatch.setenv("BOX_SHARED_LINK_ACCESS", "open")
    clients = []

    def factory():  # Box "sees" whatever the sync daemon has in the mount dir
        c = FakeBoxClient(root=mount_dir if mount_dir.exists() else FIXTURE)
        clients.append(c)
        return c

    box_api.set_box_client_factory(factory)
    out, _ = _run({"folder_id": "111"}, "approve")
    assert out["source_mode"] == "mount" and out["mount_state"] in {"mounted", "reused"}
    assert (mount_dir / "EXECUTIVE-SUMMARY.md").exists()
    assert all(c.uploads == [] for c in clients)  # never written through the API
    assert all(d["url"].startswith("https://app.box.com/s/fake") for d in out["documents"])
    notes = " | ".join(out["stage_summaries"])
    assert "source_mode=mount" in notes and "read from mount path" in notes
    assert "via mount; synced to Box" in notes
    assert "Run mode: mount" in _last_ai(out) and "upload to Box confirmed" in _last_ai(out)
    assert out["mount_synced"] is True


def test_mount_daemon_restarted_before_write(tmp_path, monkeypatch):
    mount_dir = install_fake_mount(tmp_path, monkeypatch)
    box_api.set_box_client_factory(lambda: FakeBoxClient(root=mount_dir if mount_dir.exists() else FIXTURE))
    g = compile_graph(MemorySaver())
    cfg = {"configurable": {"thread_id": uuid.uuid4().hex}}
    g.invoke({"folder_id": "111"}, cfg)
    (tmp_path / "bm-state").unlink()  # simulate MARS reaping the daemon during the ask
    out = g.invoke(Command(resume="approve"), cfg)
    notes = " | ".join(out["stage_summaries"])
    assert "write_back: daemon mounted;" in notes and out["mount_synced"] is True


def test_mount_unconfirmed_upload_is_reported_honestly(tmp_path, monkeypatch):
    install_fake_mount(tmp_path, monkeypatch)
    monkeypatch.setenv("BOX_MOUNT_UPLOAD_WAIT_S", "1")
    box_api.set_box_client_factory(lambda: FakeBoxClient())  # Box never sees the new file
    out, _ = _run({"folder_id": "111"}, "approve")
    text = _last_ai(out)
    assert out["mount_synced"] is False and "not confirmed" in text and "Saved EXECUTIVE-SUMMARY.md" not in text


def test_mount_failure_blocks_without_flag(tmp_path, monkeypatch):
    install_fake_mount(tmp_path, monkeypatch, fail=True)
    fake = FakeBoxClient()
    box_api.set_box_client_factory(lambda: fake)
    out = compile_graph().invoke({"folder_id": "111"})
    assert out["status"] == "blocked" and fake.uploads == []
    assert "Box Mount" in _last_ai(out)


def test_mount_failure_falls_back_to_api_only_with_flag(tmp_path, monkeypatch):
    install_fake_mount(tmp_path, monkeypatch, fail=True)
    monkeypatch.setenv("BOX_ALLOW_API_FALLBACK", "1")
    fake = FakeBoxClient()
    box_api.set_box_client_factory(lambda: fake)
    out, _ = _run({"folder_id": "111"}, "approve")
    assert out["source_mode"] == "api" and out["mount_state"].startswith("failed")
    assert len(fake.uploads) == 1


def test_mount_failure_without_api_blocks(tmp_path, monkeypatch):
    install_fake_mount(tmp_path, monkeypatch, fail=True)
    out = compile_graph().invoke({"folder_id": "111"})
    assert out["status"] == "blocked" and "Box Mount" in _last_ai(out)
