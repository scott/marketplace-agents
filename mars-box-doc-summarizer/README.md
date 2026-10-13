# Box Doc Summarizer (MARS LangGraph agent)

**A Box Mount demo.** The agent syncs a Box folder into its MARS sandbox with
Box Mount (private preview), reads every document from the mount, and writes
the executive summary back through the mount, where the sync daemon uploads it
to Box as a new version.

Briefs every document ## Box access modes

| Mode | When | Reads | Write-back |
|------|------|-------|------------|
| **Box Mount (primary)** | `BOX_MOUNT_BINARY_URL` + `BOX_MOUNT_SHA256` set | Synced folder at `BOX_MOUNT_PATH` | Plain file write into the folder; daemon uploads (new Box version). The agent confirms the upload by reading the file back through the API |
| Box API (explicit fallback) | No mount configured, or `BOX_ALLOW_API_FALLBACK=1` after a mount failure | REST list + download | Upload / new version |
| Fixture | input `fixture_path` | Local directory | `write_dir` |

Without `BOX_ALLOW_API_FALLBACK=1`, a mount failure ends the run as `blocked` with the reason. It never quietly switches to the API. The reply ends with a `Run mode:` line, for example `Run mode: mount (mounted: binary downloaded, sha256 verified; box-mount 0.6.0; config auth_type=jwt; status=running at /workspace/box; bootstrap synced 6 files)`. `stage_summaries` records each step.

**What still uses the Box API in mount mode:** Box Mount syncs files but can't create links. The same JWT is used read-only to look up the folder name and each file's id (for `app.box.com/file/<id>` links), to create public shared links when `BOX_SHARED_LINK_ACCESS=open`, and to confirm the summary upload.

 HTTP 401 for a tenant key; the agent retries
once on `https://inference.do-ai.run/v1` (`INFERENCE_PUBLIC_BASE_URL`). Any
fallback reason (HTTP status / exception class only) is recorded in
`stage_summaries`, `llm_note`, and a note at the end of the summary.

Links: `shared_link.url` when the file has one, else `https://app.box.com/file/<id>`.
Set `BOX_SHARED_LINK_ACCESS=open` to create public shared links for files that lack one.

## Env / secrets

| Name | Kind | Default | Notes |
|------|------|---------|-------|
| `HARNESS_INFERENCE_API_KEY` | secret | | Briefs + TL;DR via direct HTTP `stream:false`; heuristics offline |
| `BOX_JWT_CONFIG_JSON` | secret | | Developer Console JWT config (whole file) |
| `BOX_MOUNT_BINARY_URL` | secret | | Box Mount build URL (required for the demo) |
| `BOX_MOUNT_SHA256` | env | | Required with the URL; download fails closed on mismatch |
| `BOX_ALLOW_API_FALLBACK` | env | `0` | `1` allows API reads/writes if the mount fails |
| `BOX_FOLDER_ID` | env | | Default folder for `Refresh` |
| `BOX_MOUNT_PATH` | env | `/workspace/box` | Each folder syncs to `$BOX_MOUNT_PATH/<folder_id>` |
| `SUMMARY_FILENAME` | env | `EXECUTIVE-SUMMARY.md` | Excluded from inventory |
| `MAX_FILES` / `MAX_DEPTH` / `MAX_CHARS_PER_DOC` / `MAX_FILE_BYTES` | env | 50 / 3 / 20000 / 25 MB | |
| `BOX_SHARED_LINK_ACCESS` | env | empty | `open` creates public links |

The LLM only ever sees extracted document text, never env or config.

## Local

```bash
# from the repo root
pip install -r mars-box-doc-summarizer/requirements.txt
cd mars-box-doc-summarizer && pytest -q && python scripts/smoke_invoke.py
```

Offline: no API key, no network, no binary (mocked Box client + fake `box-mount` script).

## MARS

Spec: `specs/mars-box-doc-summarizer.yaml` (`size: mars-2vcpu-4gb`, `permissions.default: ask`).
Webhook trigger: `specs/mars-box-doc-summarizer-trigger.yaml`.

## Chat commands

Intake is a conversational LLM agent (DO Serverless Inference, OpenAI-compatible tool calling, with the public-endpoint retry on 401). It chats naturally with multi-turn context and calls three tools: `list_folders` (read-only, resolves names), `list_files(folder)` and `summarize_folder(folder)`. Only an explicit summary request starts a summary run, and that run still stops at the approval interrupt before anything is written. `BOX_FOLDER_ID` is used only when you ask to summarize (or list files) without naming a folder. Per-run inputs (`folder_id`, `fixture_path`) are cleared at the end of every run, so a later chat turn on the same thread never inherits them. When the LLM is unavailable, a regex fallback handles the commands below; list/show phrasing never routes to a summary.


| Say | What happens |
|-----|--------------|
| `list folders` / `what folders can you see` | Read-only Box API listing (name + id) of folders visible to the App Access Only service account. Only folders shared with (or owned by) it appear |
| `list files` / `list files in <name or id>` / `what's in <name or id>` | Name, size, type of each file, read through Box Mount (mount-primary rules; API only with `BOX_ALLOW_API_FALLBACK=1`). No summary, nothing written. Defaults to `BOX_FOLDER_ID` |
| `summarize <name or id or link>` / `refresh` | Full run with approve before write-back; reply ends with the `Run mode:` footer |
| `help` | What I can do |

List commands win over summarize whenever the message says list/show/what's in, even with a folder id in it. Folder names resolve case-insensitively (name or path). If more than one folder matches, the agent lists them with ids and asks which one; if none match, it suggests close names.
Programmatic input: `{"folder_id": "...", "auto_approve": false}`.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `Box JWT auth failed` | App authorized by an admin? Correct JSON? |
| `HTTP 404` on folder | Service account invited to the folder as Editor |
| Links point at the folder | File ids unavailable (fixture/mount without JWT) |
| Box Mount `not a Linux binary` | URL must be a direct download, not the shared-link web page |

## License

MIT
