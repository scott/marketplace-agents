# mars-pulse-diag

Minimal LangGraph agent for diagnosing whether DigitalOcean MARS injects
`{"watchlist":[]}` into `doctl agent prompt` text **independent of** the
Competitor Pulse graph.

## What it does

- State schema: **only** `messages` (with `add_messages`) — no `watchlist`,
  `competitors`, or other structured fields.
- One node replies with an `AIMessage` whose content is exactly:
  `DIAG_OK no-structured-state`

If prompt text still contains `{"watchlist":[]}`, that is **PLATFORM_INJECT**.
If text is only the DIAG_OK marker (once), that is **CLEAN**.

## Pin for MARS (scott fork)

```yaml
name: pulse-diag
agent: langgraph
template: langgraph
size: mv-2vcpu-4gb
persistent_workspace: true
env:
  FRAMEWORK_REPO: "https://github.com/scott/marketplace-agents.git"
  FRAMEWORK_REPO_SHA: "<tip SHA of main after this package lands>"
  FRAMEWORK_SUBDIR: "mars-pulse-diag"
  HARNESS_INFERENCE_BASE_URL: "https://inference.do-ai.run/v1"
  HARNESS_INFERENCE_MODEL: deepseek-v4-pro
secrets:
  HARNESS_INFERENCE_API_KEY: "<DO_INFERENCE_KEY>"
permissions:
  default: ask
```

`requirements.txt` uses `-e ./mars-pulse-diag` so pip install from monorepo
root (`/workspace`) resolves the package (MARS `FRAMEWORK_SUBDIR` layout).

## Smoke

```bash
doctl agent create --spec specs/mars-pulse-diag.yaml --name pulse-diag \
  --secret HARNESS_INFERENCE_API_KEY="$DIGITALOCEAN_ACCESS_TOKEN"
doctl agent prompt pulse-diag hi --timeout 120 --on-hitl reject -o json
```

Look for `DIAG_OK` count and presence of `{"watchlist":[]}`.

## Layout

- `langgraph.json` — graphs key **must** be `agent`
- `src/mars_pulse_diag/graph.py` — compiled `graph` export
- `pyproject.toml` — package name `mars-pulse-diag`
