# Install and run with doctl (no Agent Marketplace)

Run these LangGraph agents on DigitalOcean **Managed Agents / Harness Runtime (MARS)** by pointing `doctl` at a YAML spec. You do **not** need the Agent Marketplace — MARS clones this GitHub repo at a pinned commit, installs that agent’s `requirements.txt`, and starts the LangGraph Agent Server.

`doctl harness-runtime` is the current command name. It is also aliased as `doctl agent` / `doctl agents` / `doctl ohr`. Examples below use `doctl agent` for brevity; either form works.

Official overview: [How to Run a LangGraph Agent on Harness Runtime](https://docs.digitalocean.com/products/managed-agents/agent-harness-runtime/how-to/run-langgraph-agent/).

## Prerequisites

1. **doctl** ≥ 1.175 (or any release that includes `harness-runtime` / `agent`)
2. Authenticated DigitalOcean account with Managed Agents access:

   ```bash
   doctl auth init
   doctl agent balance   # confirm preview / balance gate is open
   ```

3. An **OpenAI-compatible inference API key** (for example DigitalOcean Gradient / Inference). The agents read:

   | Variable | Where | Purpose |
   |----------|--------|---------|
   | `HARNESS_INFERENCE_BASE_URL` | `env` in spec | Base URL (include `/v1`) |
   | `HARNESS_INFERENCE_MODEL` | `env` in spec | Model id |
   | `HARNESS_INFERENCE_API_KEY` | `secrets` | API key (never commit) |

4. This repository reachable as an HTTPS `github.com` URL. Public repos need no clone token. Private repos need GitHub auth (see [Private repositories](#private-repositories)).

## How boot works

On session create, MARS:

1. Clones `FRAMEWORK_REPO` at exact `FRAMEWORK_REPO_SHA`
2. Resolves `FRAMEWORK_SUBDIR` (this monorepo’s agent folder)
3. Runs `pip install -r requirements.txt` with the **repository root** as cwd
4. Starts LangGraph against that subdir’s `langgraph.json` (graph key must be `agent`)

Each agent’s `requirements.txt` therefore uses `-e ./mars-<agent>/` (path relative to repo root), not bare `-e .`.

## Specs in this repo

Ready-to-edit manifests live under `specs/`:

| Spec | Agent | Subdir |
|------|--------|--------|
| `specs/mars-sourced-research-desk.yaml` | Sourced Research Desk | `mars-sourced-research-desk` |
| `specs/mars-nightly-repo-audit.yaml` | Nightly Repo Audit | `mars-nightly-repo-audit` |
| `specs/mars-competitor-pulse.yaml` | Competitor Pulse | `mars-competitor-pulse` |
| `specs/mars-ghost-writer.yaml` | Ghost Writer | `mars-ghost-writer` |
| `specs/mars-box-doc-summarizer.yaml` | Box Doc Summarizer | `mars-box-doc-summarizer` |

Before create, pin a real commit and (if needed) swap the repo URL:

```bash
git rev-parse HEAD   # or the SHA you want every session to boot
```

Edit the chosen spec:

```yaml
env:
  FRAMEWORK_REPO: "https://github.com/digitalocean/marketplace-agents.git"
  FRAMEWORK_REPO_SHA: "<exact-commit-sha>"   # required — branch names fail closed
  FRAMEWORK_SUBDIR: "mars-competitor-pulse"  # match the agent you want
  HARNESS_INFERENCE_BASE_URL: "https://inference.do-ai.run/v1"
  HARNESS_INFERENCE_MODEL: deepseek-v4-pro
secrets:
  HARNESS_INFERENCE_API_KEY: "<placeholder — override with --secret>"
```

Validate client-side (no session created):

```bash
doctl agent validate specs/mars-competitor-pulse.yaml
# or inspect the fully resolved manifest:
doctl agent create --spec specs/mars-competitor-pulse.yaml --dry-run \
  --secret HARNESS_INFERENCE_API_KEY=-
```

## Create a session

Export or pipe the inference key so it never lands in the checked-in YAML:

```bash
export HARNESS_INFERENCE_API_KEY="<your-key>"

doctl agent create \
  --spec specs/mars-competitor-pulse.yaml \
  --name competitor-pulse \
  --secret HARNESS_INFERENCE_API_KEY="$HARNESS_INFERENCE_API_KEY"
```

Safer (key not in shell history):

```bash
doctl agent create \
  --spec specs/mars-competitor-pulse.yaml \
  --name competitor-pulse \
  --secret HARNESS_INFERENCE_API_KEY=@~/.secrets/do-inference.key
```

Cold start is typically ~20s (clone → pip → Agent Server). Session names must be unique on the team; remove the old session or pick a new `--name` before reusing one.

### Ghost Writer (extra secrets)

```bash
doctl agent create \
  --spec specs/mars-ghost-writer.yaml \
  --name ghost-writer \
  --secret HARNESS_INFERENCE_API_KEY=@~/.secrets/do-inference.key \
  --secret BLOG_TYPE=ghost \
  --secret BLOG_URL=https://myblog.com \
  --secret BLOG_API_KEY=@~/.secrets/ghost-admin.key
```

`BLOG_TOPIC` stays in the spec `env` block; CMS credentials stay under `secrets` / `--secret`.

### Nightly Repo Audit (Action Gateway)

The nightly-audit spec already declares `tools: [do.actions]` and an MCP allow rule so **Approve** can open a real draft GitHub PR. Connect GitHub for the team before expecting live PRs:

```bash
doctl agent auth github
```

Credentials for GitHub stay in Action Gateway Connections — not in agent `env`.

## Run the agent

### Interactive chat (recommended first smoke)

Create-and-attach in one step, or attach to an existing session:

```bash
doctl agent launch \
  --spec specs/mars-competitor-pulse.yaml \
  --name competitor-pulse \
  --secret HARNESS_INFERENCE_API_KEY=@~/.secrets/do-inference.key

# or, if the session already exists:
doctl agent launch competitor-pulse
```

Type a message and press Enter. For HITL prompts: `y`/`a` approve, `n`/`r` reject, `d` defer. Detach with `Ctrl+D` (session stays up until you `remove` it).

Example first messages by agent:

| Agent | Try |
|-------|-----|
| Competitor Pulse | `Track OpenAI, Anthropic, and Google` |
| Sourced Research Desk | A research question (outbound stays off unless you ask to send) |
| Nightly Repo Audit | Ask for a hygiene audit / cleanup PR draft on a repo |
| Ghost Writer | Brainstorm or draft a post on a topic in `BLOG_TOPIC` |

### Headless one-shot prompt

```bash
doctl agent prompt competitor-pulse "Track Cursor and Perplexity" \
  --timeout 180 \
  --on-hitl reject \
  -o json
```

`--on-hitl` is required for headless prompts that hit an approval gate (`approve` / `reject` / `defer`). Without it, an ask stops the command.

Create + prompt in one shot:

```bash
doctl agent create \
  --spec specs/mars-competitor-pulse.yaml \
  --name competitor-pulse \
  --secret HARNESS_INFERENCE_API_KEY=@~/.secrets/do-inference.key \
  --prompt "Track Cursor and Perplexity" \
  --on-hitl reject \
  --interactive=false
```

## Day-2 commands

```bash
doctl agent list
doctl agent show competitor-pulse
doctl agent logs competitor-pulse
doctl agent pause competitor-pulse
doctl agent resume competitor-pulse
doctl agent remove competitor-pulse
```

## Private repositories

If `FRAMEWORK_REPO` is private, declare a clone token under `secrets` (after `doctl agent auth github`, `oauth/github` works):

```yaml
secrets:
  HARNESS_INFERENCE_API_KEY: "<set via --secret>"
  GITHUB_TOKEN: oauth/github
```

Or pass a PAT with `--secret GITHUB_TOKEN=...`. Harness uses it only for a shallow clone of the pinned SHA.

## Agent-specific notes

- **Sourced Research Desk** — research-only by default (`outbound: none`); ask appears only when you request Slack/email send and claims are sourced.
- **Competitor Pulse** — name companies in plain English; notify/ask is off unless you ask to alert. First run establishes a baseline (“first look”), not a fake material crisis.
- **Nightly Repo Audit** — chat accepts `https://github.com/owner/name` or `owner/name` and clones that ref. Pass required secret `GITHUB_TOKEN` (contents write) for the push, plus `do.actions` and a GitHub Connection to open the draft PR. Interactive spec is `specs/mars-nightly-repo-audit.yaml` (`permissions.default: ask`). Daily cron uses `specs/mars-nightly-repo-audit-trigger.yaml` (`permissions.default: allow`); see `listings/nightly-repo-audit.md`.
- **Ghost Writer** — chat drafts need confirmation before publish; set blog secrets for CMS write.
- **Box Doc Summarizer** — `Summarize folder <id>`; approve writes `EXECUTIVE-SUMMARY.md` back to the folder. Box Mount demo: secrets `BOX_JWT_CONFIG_JSON` (JWT app, service account invited to the folder) and `BOX_MOUNT_BINARY_URL`, plus env `BOX_MOUNT_SHA256` (required; fails closed). The API is used only for links and shared links unless `BOX_ALLOW_API_FALLBACK=1`. Example:

  ```bash
  doctl agent create --spec specs/mars-box-doc-summarizer.yaml \
    --secret HARNESS_INFERENCE_API_KEY=@~/.secrets/do-inference.key \
    --secret BOX_JWT_CONFIG_JSON=@~/.secrets/box-jwt.json \
    --secret BOX_MOUNT_BINARY_URL=@~/.secrets/box-mount-url.txt
  ```

Per-agent behavior, smoke inputs, and local pytest paths are in each subdirectory’s `README.md`.

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| Boot fails immediately | `FRAMEWORK_REPO` + exact `FRAMEWORK_REPO_SHA` both set |
| `langgraph.json` / no graph | `FRAMEWORK_SUBDIR` matches the agent folder that contains `langgraph.json` |
| `ModuleNotFoundError` | Deps in that agent’s `requirements.txt`; push a new commit and update the SHA |
| Auth error from the model | `HARNESS_INFERENCE_API_KEY` via `--secret`; code reads harness env vars |
| Name already in use | `doctl agent remove <name>` or change `--name` |
| Clone fails | Public HTTPS URL, or `GITHUB_TOKEN` / `doctl agent auth github` for private repos |
| Prompt hangs on ask | Pass `--on-hitl`, or use interactive `launch` and approve in the TUI |

## Related

- Root pin summary: [README.md](./README.md)
- Example stubs next to each agent: `mars-*/mars.spec.example.yaml`
- Shop specs used above: `specs/mars-*.yaml`
