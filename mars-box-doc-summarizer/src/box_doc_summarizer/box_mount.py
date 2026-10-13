"""OPTIONAL Box Mount (private preview) mode.

Only used when secret ``BOX_MOUNT_BINARY_URL`` is set. The default Box path is
the REST API (:mod:`box_doc_summarizer.box_api`). When enabled, this module
downloads the binary, writes the JWT JSON as a 600-mode file, runs the
interactive ``box-mount config`` (stdin: ``jwt`` + JWT path), then
``box-mount mount <dir> <folder-id>``. Box Mount 0.6.0 is a two-way sync
folder, not FUSE: ``status`` reports ``<dir> | ... | status=running`` and files
appear after the first bootstrap cycle. Write-back is a plain file write into
the folder; the daemon uploads it.
"""

from __future__ import annotations

import os
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MountResult:
    ok: bool
    state: str  # mounted | reused | blocked | skipped
    path: str = ""
    message: str = ""
    steps: list = None  # safe evidence lines (no secrets, no URL)

    def __post_init__(self):
        if self.steps is None:
            self.steps = []


def mount_enabled() -> bool:
    return bool(os.environ.get("BOX_MOUNT_BINARY_URL", "").strip())


def default_binary_path() -> Path:
    return Path(os.path.expanduser("~/.local/bin/box-mount"))


def mount_path(folder_id: str = "") -> str:
    """One sync folder per Box folder: ``$BOX_MOUNT_PATH/<folder_id>``."""
    base = os.environ.get("BOX_MOUNT_PATH", "/workspace/box").rstrip("/")
    return f"{base}/{folder_id}" if folder_id else base


def _run(binary: str, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run([binary, *args], capture_output=True, text=True, timeout=timeout)


def _status_running(out: str, path: str, folder_id: str = "") -> bool:
    """Box Mount 0.6.0: ``<dir> | box_folder_id=<id> | pid=<pid> | status=running``."""
    for line in out.splitlines():
        if line.split("|")[0].strip() != path or "status=running" not in line:
            continue
        if folder_id and f"box_folder_id={folder_id}" not in line:
            continue
        return True
    return False


def _wait_bootstrap(path: str, deadline: float) -> None:
    """Sync folder (not FUSE): files appear after the first bootstrap cycle (~6s)."""
    p = Path(path)
    while time.time() < deadline:
        if any(not c.name.startswith(".") for c in p.iterdir()):
            return
        time.sleep(1)


def _download_binary(url: str, dest: Path) -> None:
    """Download the preview build. Accepts a raw ELF or a ``.tar.gz`` holding ``box-mount``
    (Box ships ``box-mount-<ver>-linux-<arch>.tar.gz``). Optional ``BOX_MOUNT_SHA256``
    verifies the downloaded artifact."""
    import hashlib
    import io
    import tarfile

    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    want_pre = os.environ.get("BOX_MOUNT_SHA256", "").strip()
    if not want_pre:
        raise RuntimeError("BOX_MOUNT_SHA256 is required when BOX_MOUNT_BINARY_URL is set.")
    try:
        resp = requests.get(url, timeout=600, allow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:  # never echo the (secret) URL
        code = getattr(getattr(exc, "response", None), "status_code", None)
        raise RuntimeError(f"Box Mount download failed ({type(exc).__name__}{', HTTP ' + str(code) if code else ''}).") from None
    data = resp.content
    want = os.environ.get("BOX_MOUNT_SHA256", "").strip().lower()
    if not want:
        raise RuntimeError("BOX_MOUNT_SHA256 is required when BOX_MOUNT_BINARY_URL is set.")
    if hashlib.sha256(data).hexdigest() != want:
        raise RuntimeError("Box Mount download failed SHA256 check.")
    if data[:2] == b"\x1f\x8b":
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            member = next(
                (m for m in tar.getmembers() if m.isfile() and Path(m.name).name == "box-mount"),
                None,
            )
            if member is None:
                raise RuntimeError("Box Mount archive has no box-mount binary.")
            data = tar.extractfile(member).read()
    if data[:4] != b"\x7fELF":
        raise RuntimeError("Box Mount download is not a Linux binary (check the direct-download URL).")
    dest.write_bytes(data)
    os.chmod(dest, stat.S_IRWXU)


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def ensure_mount(folder_id: str, *, binary: str | None = None, home: str | None = None) -> MountResult:
    if not mount_enabled() and binary is None:
        return MountResult(ok=False, state="skipped", message="Box Mount not configured.")
    target = mount_path(str(folder_id))
    bin_path = Path(binary) if binary else default_binary_path()
    steps: list[str] = []

    def blocked(msg: str) -> MountResult:
        return MountResult(ok=False, state="blocked", path=target, message=msg[:300], steps=steps)

    try:
        if not bin_path.exists():
            _download_binary(os.environ["BOX_MOUNT_BINARY_URL"], bin_path)
            steps.append("binary downloaded, sha256 verified")
        else:
            steps.append("binary present")
        ver = _run(str(bin_path), "--version", timeout=30)
        if ver.returncode == 0 and ver.stdout.strip():
            steps.append(ver.stdout.strip().splitlines()[0][:40])
        status = _run(str(bin_path), "status")
        if status.returncode == 0 and _status_running(status.stdout, target, str(folder_id)):
            steps.append(f"mount already running at {target}")
            return MountResult(ok=True, state="reused", path=target, steps=steps)

        jwt_json = os.environ.get("BOX_JWT_CONFIG_JSON", "").strip()
        if not jwt_json:
            return blocked("BOX_JWT_CONFIG_JSON is not set.")
        base = Path(home or os.path.expanduser("~")) / ".box-mount"
        jwt_path = base / "jwt-config.json"
        _write_private(jwt_path, jwt_json)  # must stay on disk for the sync daemon
        # `box-mount config` is interactive (no flags): auth type, then JWT config path.
        cfg = subprocess.run(
            [str(bin_path), "config"],
            input=f"jwt\n{jwt_path}\n",
            capture_output=True,
            text=True,
            timeout=60,
        )
        if cfg.returncode != 0:
            return blocked("box-mount config failed: " + (cfg.stderr or cfg.stdout or "").strip()[:200])
        cfg_file = base / "box-config.json"
        if cfg_file.exists():
            os.chmod(cfg_file, 0o600)
        steps.append("config auth_type=jwt")
        Path(target).mkdir(parents=True, exist_ok=True)
        res = _run(str(bin_path), "mount", target, str(folder_id))
        if res.returncode != 0:
            return blocked("box-mount mount failed: " + (res.stderr or res.stdout or "").strip()[:200])
        deadline = time.time() + float(os.environ.get("BOX_MOUNT_SYNC_TIMEOUT_S", "300"))
        while time.time() < deadline:
            st = _run(str(bin_path), "status")
            if st.returncode == 0 and _status_running(st.stdout, target, str(folder_id)):
                steps.append(f"status=running at {target}")
                _wait_bootstrap(target, min(deadline, time.time() + float(os.environ.get("BOX_MOUNT_BOOTSTRAP_S", "30"))))
                n = sum(1 for p in Path(target).rglob("*") if p.is_file() and not any(x.startswith(".") for x in p.relative_to(target).parts))
                steps.append(f"bootstrap synced {n} files")
                return MountResult(ok=True, state="mounted", path=target, steps=steps)
            time.sleep(2)
        return blocked("Box Mount did not reach status=running in time.")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        return MountResult(ok=False, state="blocked", path=target, message=msg[:300], steps=steps)
