"""Shared fakes: in-memory Box client and fixture paths."""

from __future__ import annotations

from pathlib import Path

from box_doc_summarizer.box_api import BoxFolder, BoxItem

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_folder"


class FakeBoxClient:
    """In-memory Box folder built from a local directory (no network)."""

    def __init__(self, root: Path = FIXTURE, folder_id: str = "111", shared: dict[str, str] | None = None, folders=None):
        self.folders = folders if folders is not None else [("111", "box-doc-summarizer-test", "box-doc-summarizer-test")]
        self.root = Path(root)
        self.folder_id = folder_id
        self.shared = shared or {}
        self.uploads: list[dict] = []
        self.shared_link_calls: list[str] = []
        self.files: dict[str, tuple[str, bytes]] = {}
        n = 9000
        for p in sorted(self.root.rglob("*")):
            if p.is_file():
                n += 1
                rel = p.relative_to(self.root).as_posix()
                self.files[str(n)] = (rel, p.read_bytes())

    def get_folder(self, folder_id: str) -> BoxFolder:
        return BoxFolder(id=folder_id, name="Sample Folder")

    def list_files(self, folder_id: str, *, max_depth: int = 3, max_items: int = 500):
        return [
            BoxItem(id=fid, name=rel.rsplit("/", 1)[-1], path=rel, size=len(data), shared_link_url=self.shared.get(rel, ""))
            for fid, (rel, data) in self.files.items()
        ][:max_items]

    def download(self, file_id: str) -> bytes:
        return self.files[file_id][1]

    def upload_text(self, folder_id: str, name: str, content: str, *, existing_file_id: str = ""):
        fid = existing_file_id or "77777"
        self.uploads.append({"folder_id": folder_id, "name": name, "content": content, "existing_file_id": existing_file_id})
        self.files[fid] = (name, content.encode())
        return BoxItem(id=fid, name=name, path=name)

    def ensure_shared_link(self, file_id: str, access: str = "open") -> str:
        self.shared_link_calls.append(file_id)
        return f"https://app.box.com/s/fake{file_id}"

    def list_folders(self, root_id: str = "0", *, max_depth: int = 3, max_items: int = 200):
        return [BoxItem(id=i, name=n, path=p, type="folder") for i, n, p in self.folders][:max_items]
