"""Install a fake ``box-mount`` CLI whose mount copies the sample fixture into the mount dir."""

from __future__ import annotations

from pathlib import Path

from box_doc_summarizer import box_mount
from helpers import FIXTURE

SCRIPT = """#!/bin/sh
case "$1" in
  config) read AUTH; read JWTPATH; [ "$AUTH" = "jwt" ] || exit 4 ;;
  status) if [ -f "$FAKE_BM_STATE" ]; then cat "$FAKE_BM_STATE"; else echo "No mount found."; fi ;;
  mount)
    [ -n "$FAKE_BM_FAIL" ] && { echo "jwt auth failed" >&2; exit 2; }
    mkdir -p "$2" && cp -R "$FAKE_BM_SRC"/. "$2"/ && echo "$2 | box_folder_id=$3 | pid=1 | status=running" > "$FAKE_BM_STATE" ;;
esac
"""


def install_fake_mount(tmp_path: Path, monkeypatch, *, fail: bool = False) -> Path:
    b = tmp_path / "bin" / "box-mount"
    b.parent.mkdir(exist_ok=True)
    b.write_text(SCRIPT)
    b.chmod(0o755)
    mount_dir = tmp_path / "box" / "111"  # per-folder sync dir under BOX_MOUNT_PATH
    monkeypatch.setenv("FAKE_BM_STATE", str(tmp_path / "bm-state"))
    monkeypatch.setenv("FAKE_BM_SRC", str(FIXTURE))
    monkeypatch.setenv("BOX_MOUNT_PATH", str(tmp_path / "box"))
    monkeypatch.setenv("BOX_MOUNT_BINARY_URL", "https://example.invalid/box-mount.tar.gz")
    monkeypatch.setenv("BOX_JWT_CONFIG_JSON", "{}")
    monkeypatch.setenv("BOX_MOUNT_BOOTSTRAP_S", "2")
    monkeypatch.setenv("BOX_MOUNT_UPLOAD_WAIT_S", "5")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(box_mount, "default_binary_path", lambda: b)
    if fail:
        monkeypatch.setenv("FAKE_BM_FAIL", "1")
    return mount_dir
