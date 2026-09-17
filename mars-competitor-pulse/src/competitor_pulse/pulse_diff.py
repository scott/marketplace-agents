"""Fixture paths, snapshot load, baseline diff helpers."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from pathlib import Path
from typing import Any

_MODULE_KEYS = ("site", "pricing", "changelog", "careers")

_DOCTYPE_RE = re.compile(r"<!DOCTYPE[^>]*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ERROR_MARKERS = (
    "system downtime",
    "service unavailable",
    "503 service",
    "404 not found",
    "access denied",
    "maintenance",
    "temporarily unavailable",
)


def package_root() -> Path:
    """Repo root (parent of src/)."""
    return Path(__file__).resolve().parents[2]


def default_fixture_dir() -> Path:
    return package_root() / "fixtures"


def default_snapshot_dir() -> Path:
    return default_fixture_dir() / "snapshots"


def default_baseline_path() -> Path:
    return default_fixture_dir() / "baselines" / "baseline.json"


def quiet_baseline_path() -> Path:
    return default_fixture_dir() / "baselines" / "quiet.json"


def material_baseline_path() -> Path:
    return default_fixture_dir() / "baselines" / "material.json"


def default_competitors() -> list[dict[str, Any]]:
    path = default_fixture_dir() / "competitors.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


def spacexai_competitors() -> list[dict[str, Any]]:
    path = default_fixture_dir() / "competitors_spacexai.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return []


# Back-compat aliases (legacy names; not state/schema keys).
default_watchlist = default_competitors
spacexai_watchlist = spacexai_competitors


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def snapshot_filename(competitor: str, module: str) -> str:
    """Map competitor+module to fixture filename."""
    slug = _slug(competitor)
    ext = "txt" if module == "changelog" else "html"
    return f"{slug}_{module}.{ext}"


def load_fixture_snapshot(
    snapshot_dir: Path, competitor: str, module: str
) -> dict[str, Any] | None:
    fname = snapshot_filename(competitor, module)
    path = snapshot_dir / fname
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    return {
        "competitor": competitor,
        "module": module,
        "text": text,
        "content_hash": content_hash(text),
        "ok": True,
        "snapshot_file": fname,
        "source": "fixture",
    }


def load_baseline(path: Path) -> dict[str, dict[str, Any]]:
    """Index baseline entries by competitor|module."""
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries") or []
    out: dict[str, dict[str, Any]] = {}
    for e in entries:
        key = f"{e.get('competitor')}|{e.get('module')}"
        out[key] = e
    return out


def strip_html(text: str) -> str:
    """Remove tags/DOCTYPE and collapse whitespace for operator-facing copy."""
    if not text:
        return ""
    cleaned = _DOCTYPE_RE.sub(" ", text)
    cleaned = _TAG_RE.sub(" ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = _WS_RE.sub(" ", cleaned).strip()
    return cleaned


def extract_title(text: str) -> str:
    """Best-effort page title from HTML."""
    m = re.search(r"<title[^>]*>([^<]+)</title>", text or "", re.I)
    if m:
        return strip_html(m.group(1))[:120]
    return ""


def detect_page_issue(text: str) -> str | None:
    """Return a short issue label when the page looks like an error/downtime page."""
    plain = strip_html(text).lower()
    if not plain:
        return "empty or unreachable page"
    for marker in _ERROR_MARKERS:
        if marker in plain:
            return marker
    if "<!doctype" in (text or "").lower() and len(plain) < 80:
        return "minimal HTML response (possible error page)"
    return None


def describe_snapshot(module: str, text: str) -> str:
    """Human first-look summary for a captured page."""
    issue = detect_page_issue(text)
    if issue:
        title = extract_title(text)
        if title:
            return f"{module}: looks like an error/downtime page — “{title}” ({issue})."
        return f"{module}: looks like an error/downtime page ({issue})."

    if module == "changelog":
        first = strip_html(text).splitlines()[0] if text.strip() else "changelog"
        return f"changelog: latest entry starts with “{first[:100]}”."

    plain = strip_html(text)
    title = extract_title(text)
    if module == "pricing":
        if title:
            return f"pricing page titled “{title}”."
        return "pricing page captured."
    if module == "careers":
        if title:
            return f"careers page titled “{title}”."
        return "careers page captured."
    # site
    if title:
        snippet = plain.replace(title, "", 1).strip()[:80]
        if snippet:
            return f"homepage “{title}” — {snippet}…"
        return f"homepage titled “{title}”."
    return f"homepage captured ({len(plain)} chars of visible text)."


def summarize_change(
    module: str,
    old_excerpt: str,
    new_text: str,
    *,
    is_baseline_capture: bool = False,
) -> str:
    """Short human delta summary (deterministic, no LLM)."""
    if is_baseline_capture:
        return describe_snapshot(module, new_text)

    plain_new = strip_html(new_text)
    issue = detect_page_issue(new_text)
    if issue:
        title = extract_title(new_text)
        if title:
            return f"Page now shows error/downtime content — “{title}”."
        return f"Page now looks like an error/downtime response ({issue})."

    if module == "pricing":
        title = extract_title(new_text)
        if title:
            return f"Pricing page updated — “{title}”."
        return "Pricing page content changed."
    if module == "changelog":
        first = plain_new.splitlines()[0] if plain_new else "changelog update"
        return f"Changelog update: {first[:120]}"
    if module == "careers":
        title = extract_title(new_text)
        if title:
            return f"Careers page updated — “{title}”."
        return "Careers page content changed."
    # site
    title = extract_title(new_text)
    if title:
        return f"Homepage updated — “{title}”."
    snippet = plain_new[:100]
    return f"Homepage copy changed: {snippet}…" if snippet else "Homepage copy changed."


def change_type(module: str) -> str:
    return {
        "pricing": "pricing_change",
        "changelog": "changelog_entry",
        "careers": "careers_change",
        "site": "site_copy_change",
    }.get(module, "content_change")


def counterposition_line(delta: dict[str, Any]) -> str:
    """One useful counterposition line — no internal change_type boilerplate."""
    comp = delta.get("competitor") or "Competitor"
    module = delta.get("module") or "page"
    summary = delta.get("summary") or ""
    if delta.get("is_baseline_capture"):
        return ""
    if module == "pricing":
        return f"{comp} moved pricing — sanity-check our tier story and any deal desk talk tracks."
    if module == "changelog":
        return f"{comp} shipped something new — decide if we need a competitive response in GTM."
    if module == "careers":
        return f"{comp} hiring signal on careers — worth a quick check for team focus areas."
    if "error" in summary.lower() or "downtime" in summary.lower():
        return f"{comp} site may be unstable — hold outbound until their page is back."
    return f"{comp} homepage shift — skim for positioning changes before the next customer call."


def diff_snapshots(
    snapshots: list[dict[str, Any]],
    baseline_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return deltas where content_hash differs from baseline (or new module)."""
    deltas: list[dict[str, Any]] = []
    for snap in snapshots:
        if not snap.get("ok"):
            continue
        comp = snap.get("competitor") or ""
        module = snap.get("module") or ""
        key = f"{comp}|{module}"
        base = baseline_index.get(key)
        new_hash = snap.get("content_hash") or content_hash(snap.get("text") or "")
        if base and base.get("content_hash") == new_hash:
            continue
        old_excerpt = (base or {}).get("text_excerpt") or ""
        new_text = snap.get("text") or ""
        is_baseline_capture = base is None
        deltas.append(
            {
                "competitor": comp,
                "module": module,
                "change_type": change_type(module),
                "summary": summarize_change(
                    module,
                    old_excerpt,
                    new_text,
                    is_baseline_capture=is_baseline_capture,
                ),
                "evidence_url": snap.get("url") or (base or {}).get("url") or "",
                "old_hash": (base or {}).get("content_hash") or "",
                "new_hash": new_hash,
                "is_baseline_capture": is_baseline_capture,
            }
        )
    return deltas


def split_deltas(deltas: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separate first-baseline captures from real material changes."""
    captures = [d for d in deltas if d.get("is_baseline_capture")]
    changes = [d for d in deltas if not d.get("is_baseline_capture")]
    return captures, changes


def allow_network() -> bool:
    """Network fetch allowed only when ALLOW_NET is truthy (default off for tests)."""
    val = (os.environ.get("ALLOW_NET") or "0").strip().lower()
    return val in {"1", "true", "yes", "on"}


def modules_from_competitors(competitors: list[dict[str, Any]]) -> list[str]:
    found: list[str] = []
    for item in competitors:
        urls = item.get("urls") or {}
        for m in _MODULE_KEYS:
            if urls.get(m) and m not in found:
                found.append(m)
    if not found:
        found = ["site"]
    return found


modules_from_watchlist = modules_from_competitors
