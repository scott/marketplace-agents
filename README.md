# marketplace-agents

LangGraph agents shaped for DigitalOcean MARS (Managed Agents / Harness Runtime).

Each agent lives in its own subdirectory. Pin with the same `FRAMEWORK_REPO` + `FRAMEWORK_REPO_SHA` and set `FRAMEWORK_SUBDIR` to the agent folder.

**Adding or listing a new agent for the Marketplace:** see **[AGENTS.md](./AGENTS.md)**. Repeatable Cursor workflows: [skills/README.md](./skills/README.md) (`./scripts/install-cursor-skills.sh`).

| Subdir | Agent |
|--------|--------|
| `mars-sourced-research-desk` | Sourced Research Desk |
| `mars-nightly-repo-audit` | Nightly Repo Audit |
| `mars-competitor-pulse` | Competitor Pulse |
| `mars-ghost-writer` | Ghost Writer |
| `mars-box-doc-summarizer` | Box Doc Summarizer |

## Install and run with doctl (no Marketplace)

To create and chat with these agents from the CLI — without the Agent Marketplace — see **[DOCTL.md](./DOCTL.md)**. Short path:

```bash
# pin FRAMEWORK_REPO_SHA in the chosen specs/*.yaml, then:
doctl agent create \
  --spec specs/mars-competitor-pulse.yaml \
  --name competitor-pulse \
  --secret HARNESS_INFERENCE_API_KEY=@~/.secrets/do-inference.key

doctl agent launch competitor-pulse
```

`doctl agent` is an alias of `doctl harness-runtime`. Specs for all four agents live under `specs/`.

## MARS pin (per agent)

```yaml
agent: langgraph
template: langgraph
env:
  FRAMEWORK_REPO: "https://github.com/digitalocean/marketplace-agents.git"
  FRAMEWORK_REPO_SHA: "<exact-commit-sha>"
  FRAMEWORK_SUBDIR: "mars-competitor-pulse"  # or mars-sourced-research-desk / mars-nightly-repo-audit / mars-ghost-writer / mars-box-doc-summarizer
  HARNESS_INFERENCE_BASE_URL: "https://inference.do-ai.run/v1"
  HARNESS_INFERENCE_MODEL: deepseek-v4-pro
secrets:
  HARNESS_INFERENCE_API_KEY: "<set via doctl --secret>"
permissions:
  default: ask
```

Each subdirectory `langgraph.json` registers the graph as **`agent`** (required by the harness invoke path). Install deps via that subdir’s `requirements.txt` (includes `-e .`).

## Monorepo install note

MARS installs `requirements.txt` with the **repository root** as the working directory (even when `FRAMEWORK_SUBDIR` is set). Each agent’s `requirements.txt` therefore uses `-e ./mars-<agent>/` (path relative to repo root), not bare `-e .`.
