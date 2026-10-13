"""Box REST API client (JWT server auth, service account).

Primary Box path for the agent: list a folder recursively, download files,
build per-file links, and upload / version ``EXECUTIVE-SUMMARY.md`` back.

Credentials come from secret ``BOX_JWT_CONFIG_JSON`` (the Developer Console
JWT config JSON). The private key is decrypted in memory only; nothing is
written to disk and nothing from the config is ever passed to the LLM.

Tests inject a fake with :func:`set_box_client_factory`.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

API_BASE = "https://api.box.com/2.0"
UPLOAD_BASE = "https://upload.box.com/api/2.0"
TOKEN_URL = "https://api.box.com/oauth2/token"
ITEM_FIELDS = "id,type,name,size,modified_at,shared_link"


class BoxError(RuntimeError):
    """Box API or auth failure (message is safe to show; never contains secrets)."""


@dataclass
class BoxItem:
    id: str
    name: str
    path: str  # relative to the summarized folder, e.g. "Islands/Maui.docx"
    type: str = "file"
    size: int = 0
    modified_at: str = ""
    shared_link_url: str = ""

    @property
    def url(self) -> str:
        return file_url(self.id, self.shared_link_url)


@dataclass
class BoxFolder:
    id: str
    name: str
    shared_link_url: str = ""
    items: list[BoxItem] = field(default_factory=list)

    @property
    def url(self) -> str:
        return self.shared_link_url or folder_url(self.id)


def file_url(file_id: str, shared_link_url: str = "") -> str:
    return shared_link_url or f"https://app.box.com/file/{file_id}"


def folder_url(folder_id: str) -> str:
    return f"https://app.box.com/folder/{folder_id}"


class BoxClient(Protocol):
    def get_folder(self, folder_id: str) -> BoxFolder: ...

    def list_files(self, folder_id: str, *, max_depth: int = 3, max_items: int = 500) -> list[BoxItem]: ...

    def download(self, file_id: str) -> bytes: ...

    def list_folders(self, root_id: str = "0", *, max_depth: int = 3, max_items: int = 200) -> list[BoxItem]: ...

    def upload_text(self, folder_id: str, name: str, content: str, *, existing_file_id: str = "") -> BoxItem: ...

    def ensure_shared_link(self, file_id: str, access: str = "open") -> str: ...


def load_jwt_config(raw: str | None = None) -> dict[str, Any]:
    raw = raw if raw is not None else os.environ.get("BOX_JWT_CONFIG_JSON", "")
    raw = (raw or "").strip()
    if not raw:
        raise BoxError("BOX_JWT_CONFIG_JSON is not set.")
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BoxError("BOX_JWT_CONFIG_JSON is not valid JSON.") from exc
    settings = cfg.get("boxAppSettings") or {}
    auth = settings.get("appAuth") or {}
    missing = [
        k
        for k, v in {
            "boxAppSettings.clientID": settings.get("clientID"),
            "boxAppSettings.clientSecret": settings.get("clientSecret"),
            "boxAppSettings.appAuth.publicKeyID": auth.get("publicKeyID"),
            "boxAppSettings.appAuth.privateKey": auth.get("privateKey"),
            "enterpriseID": cfg.get("enterpriseID"),
        }.items()
        if not v
    ]
    if missing:
        raise BoxError("BOX_JWT_CONFIG_JSON is missing: " + ", ".join(missing))
    return cfg


class RestBoxClient:
    """Minimal Box API client using JWT (enterprise service account)."""

    def __init__(self, config: dict[str, Any], *, session: Any = None, timeout: float = 60.0):
        import requests

        self._cfg = config
        self._session = session or requests.Session()
        self._timeout = timeout
        self._token = ""
        self._token_exp = 0.0

    # -- auth -------------------------------------------------------------
    def _assertion(self) -> str:
        import jwt
        from cryptography.hazmat.primitives import serialization

        settings = self._cfg["boxAppSettings"]
        auth = settings["appAuth"]
        passphrase = auth.get("passphrase") or None
        key = serialization.load_pem_private_key(
            auth["privateKey"].encode("utf-8"),
            password=passphrase.encode("utf-8") if passphrase else None,
        )
        now = int(time.time())
        claims = {
            "iss": settings["clientID"],
            "sub": str(self._cfg["enterpriseID"]),
            "box_sub_type": "enterprise",
            "aud": TOKEN_URL,
            "jti": uuid.uuid4().hex + uuid.uuid4().hex,
            "exp": now + 45,
        }
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": auth["publicKeyID"]})

    def _access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        settings = self._cfg["boxAppSettings"]
        resp = self._session.post(
            TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": self._assertion(),
                "client_id": settings["clientID"],
                "client_secret": settings["clientSecret"],
            },
            timeout=self._timeout,
        )
        if resp.status_code >= 400:
            hint = ""
            try:
                hint = resp.json().get("error_description") or resp.json().get("error") or ""
            except Exception:  # noqa: BLE001
                pass
            raise BoxError(f"Box JWT auth failed (HTTP {resp.status_code}). {hint}".strip())
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + float(data.get("expires_in", 3600))
        return self._token

    def _request(self, method: str, url: str, **kw: Any):
        headers = kw.pop("headers", {}) or {}
        headers["Authorization"] = f"Bearer {self._access_token()}"
        resp = self._session.request(method, url, headers=headers, timeout=self._timeout, **kw)
        if resp.status_code >= 400:
            msg = ""
            try:
                body = resp.json()
                msg = body.get("message") or body.get("code") or ""
            except Exception:  # noqa: BLE001
                pass
            raise BoxError(f"Box API {method} {url.split('?')[0]} failed (HTTP {resp.status_code}). {msg}".strip())
        return resp

    # -- reads ------------------------------------------------------------
    def get_folder(self, folder_id: str) -> BoxFolder:
        data = self._request("GET", f"{API_BASE}/folders/{folder_id}", params={"fields": "id,name,shared_link"}).json()
        return BoxFolder(
            id=str(data["id"]),
            name=data.get("name") or str(folder_id),
            shared_link_url=((data.get("shared_link") or {}).get("url") or ""),
        )

    def _list_children(self, folder_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = 0
        while True:
            data = self._request(
                "GET",
                f"{API_BASE}/folders/{folder_id}/items",
                params={"fields": ITEM_FIELDS, "limit": 1000, "offset": offset},
            ).json()
            entries = data.get("entries") or []
            out.extend(entries)
            offset += len(entries)
            if not entries or offset >= int(data.get("total_count") or 0):
                return out

    def list_files(self, folder_id: str, *, max_depth: int = 3, max_items: int = 500) -> list[BoxItem]:
        files: list[BoxItem] = []
        queue: list[tuple[str, str, int]] = [(str(folder_id), "", 0)]
        while queue and len(files) < max_items:
            fid, prefix, depth = queue.pop(0)
            for entry in self._list_children(fid):
                name = entry.get("name") or ""
                rel = f"{prefix}{name}"
                if entry.get("type") == "folder":
                    if depth + 1 < max_depth:
                        queue.append((str(entry["id"]), rel + "/", depth + 1))
                    continue
                if entry.get("type") != "file":
                    continue
                files.append(
                    BoxItem(
                        id=str(entry["id"]),
                        name=name,
                        path=rel,
                        size=int(entry.get("size") or 0),
                        modified_at=entry.get("modified_at") or "",
                        shared_link_url=((entry.get("shared_link") or {}).get("url") or ""),
                    )
                )
                if len(files) >= max_items:
                    break
        return files

    def list_folders(self, root_id: str = "0", *, max_depth: int = 3, max_items: int = 200) -> list[BoxItem]:
        """Folders visible to this identity (App Access Only: only folders shared with
        or owned by the service account), breadth-first from ``root_id``."""
        out: list[BoxItem] = []
        queue: list[tuple[str, str, int]] = [(str(root_id), "", 0)]
        while queue and len(out) < max_items:
            fid, prefix, depth = queue.pop(0)
            for entry in self._list_children(fid):
                if entry.get("type") != "folder":
                    continue
                rel = f"{prefix}{entry.get('name') or ''}"
                out.append(BoxItem(id=str(entry["id"]), name=entry.get("name") or "", path=rel, type="folder"))
                if depth + 1 < max_depth:
                    queue.append((str(entry["id"]), rel + "/", depth + 1))
                if len(out) >= max_items:
                    break
        return out

    def download(self, file_id: str) -> bytes:
        return self._request("GET", f"{API_BASE}/files/{file_id}/content", allow_redirects=True).content

    # -- writes -----------------------------------------------------------
    def upload_text(self, folder_id: str, name: str, content: str, *, existing_file_id: str = "") -> BoxItem:
        payload = content.encode("utf-8")
        if existing_file_id:
            url = f"{UPLOAD_BASE}/files/{existing_file_id}/content"
            attrs = {"name": name}
        else:
            url = f"{UPLOAD_BASE}/files/content"
            attrs = {"name": name, "parent": {"id": str(folder_id)}}
        resp = self._request(
            "POST",
            url,
            data={"attributes": json.dumps(attrs)},
            files={"file": (name, payload, "text/markdown")},
        )
        entry = (resp.json().get("entries") or [{}])[0]
        return BoxItem(
            id=str(entry.get("id") or existing_file_id),
            name=name,
            path=name,
            size=len(payload),
            modified_at=entry.get("modified_at") or "",
            shared_link_url=((entry.get("shared_link") or {}).get("url") or ""),
        )

    def ensure_shared_link(self, file_id: str, access: str = "open") -> str:
        data = self._request(
            "PUT",
            f"{API_BASE}/files/{file_id}",
            params={"fields": "shared_link"},
            json={"shared_link": {"access": access}},
        ).json()
        return (data.get("shared_link") or {}).get("url") or ""


_factory: Callable[[], BoxClient] | None = None


def set_box_client_factory(factory: Callable[[], BoxClient] | None) -> None:
    """Inject a fake client (tests / smoke). ``None`` restores the real JWT client."""
    global _factory
    _factory = factory


def box_api_configured() -> bool:
    return _factory is not None or bool(os.environ.get("BOX_JWT_CONFIG_JSON", "").strip())


def get_box_client() -> BoxClient:
    if _factory is not None:
        return _factory()
    return RestBoxClient(load_jwt_config())
