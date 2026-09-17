# Ghost Writer

Research topics, draft HTML blog posts, and publish to Ghost or WordPress — with explicit human approval before publish in chat mode. LangGraph agent shaped for DigitalOcean MARS (Managed Agents / Harness Runtime).

Ported from [digitalocean/ghost-writer](https://github.com/digitalocean/ghost-writer) branch `mars-deploy`.

## What it does

- **Chat mode (MARS default):** brainstorm → web research → full draft in chat → publish only after you confirm
- **Autonomous publish path:** send sentinel `__GW_PUBLISH__` or set `GW_RUN_MODE=publish` to run the scheduler-style write-and-publish pipeline
- **Tools:** `search_web` (DuckDuckGo), `publish_to_blog` (Ghost / WordPress with optional feature image)
- **Voice:** professional blog author/editor — no em-dashes, SEO-aware HTML, never publishes without explicit confirmation in chat

## MARS pin

```yaml
agent: langgraph
template: langgraph
env:
  FRAMEWORK_REPO: "https://github.com/digitalocean/marketplace-agents.git"
  FRAMEWORK_REPO_SHA: "<exact-commit-sha>"
  FRAMEWORK_SUBDIR: "mars-ghost-writer"
  HARNESS_INFERENCE_BASE_URL: "https://inference.do-ai.run/v1"
  HARNESS_INFERENCE_MODEL: deepseek-v4-pro
  BLOG_TOPIC: "AI, Cloud Computing, DevOps"
secrets:
  HARNESS_INFERENCE_API_KEY: "<set via doctl --secret>"
  BLOG_TYPE: "ghost"          # or wordpress
  BLOG_URL: "https://myblog.com"
  BLOG_API_KEY: "id:secret"   # Ghost id:secret or WP user:app_password
permissions:
  default: ask
```

`langgraph.json` registers the graph as **`agent`**. MARS installs deps from `requirements.txt` at the **repo root** (includes `-e ./mars-ghost-writer`).

## Environment

| Variable | Description |
|----------|-------------|
| `HARNESS_INFERENCE_*` | Preferred LLM env (mapped to Gradient vars at graph startup) |
| `OPENAI_*` | Fallback when harness vars unset |
| `BLOG_TOPIC` | Comma-separated topics for autonomous publish |
| `BLOG_TYPE` / `BLOG_URL` / `BLOG_API_KEY` | CMS credentials for publish |
| `GW_RUN_MODE=publish` | Route every invoke to autonomous publish |
| `ALLOW_NET` | Tests default offline; live search needs network |

## Local install and test

From the monorepo root (MARS-style install path):

```bash
pip install -r mars-ghost-writer/requirements.txt
cd mars-ghost-writer
export ALLOW_NET=0
pytest -q
python scripts/smoke_invoke.py
```

Optional live LLM + search:

```bash
export HARNESS_INFERENCE_BASE_URL=...
export HARNESS_INFERENCE_MODEL=...
export HARNESS_INFERENCE_API_KEY=...
export ALLOW_NET=1
```

## Graph routing

```
user message → ghost_writer node → AIMessage
  - normal text → Agent.process_message (chat)
  - __GW_PUBLISH__ or GW_RUN_MODE=publish → Agent.generate_and_publish
```

## Intentionally not in this MARS subdir

Standalone Ghost Writer server pieces from `mars-deploy` are omitted here (FastAPI `__main__.py`, Textual TUI, Docker/App Platform deploy manifests, APScheduler). MARS serves the compiled LangGraph graph only; Reed smoke-tests deploy separately.

Spec stubs: `mars.spec.example.yaml` and `specs/mars-ghost-writer.yaml`.
