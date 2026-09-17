# Ghost Writer — research, draft, publish (with your OK)

**For** content operators who want an AI blog author that researches the web, writes full HTML drafts, and publishes to Ghost or WordPress — without surprise posts.

**Job-to-be-done:** Brainstorm a topic → search for current angles → present a complete draft in chat → **publish only after you say so** (or trigger autonomous publish via `__GW_PUBLISH__` / `GW_RUN_MODE=publish`).

**Why MARS / LangGraph:** Same MARS-shaped LangGraph family as Research Desk, Nightly Audit, and Competitor Pulse: one compiled graph keyed **`agent`**, harness-native inference env, pin via `FRAMEWORK_SUBDIR=mars-ghost-writer`.

---

## What you get

- Interactive chat: brainstorm → research → draft → explicit publish confirmation
- Autonomous publish path for scheduled / headless runs (`__GW_PUBLISH__` sentinel)
- Ghost and WordPress CMS clients with optional AI feature images
- Draft auto-capture from LLM output (title + tags only needed at publish time)
- Offline unit tests (`ALLOW_NET=0`) — no API key required for pytest
- Harness LLM env: `HARNESS_INFERENCE_*` first, `OPENAI_*` fallback

## What you don't (v1 honesty)

- **No standalone FastAPI/TUI in this subdir** — MARS graph only; original server lives in upstream ghost-writer repo
- No publish without explicit chat confirmation (chat path) or publish sentinel / `GW_RUN_MODE`
- Web search needs network (`ALLOW_NET=1` or live MARS egress); tests mock search offline
- Blog credentials required for real publish (`BLOG_TYPE`, `BLOG_URL`, `BLOG_API_KEY`)

---

## Getting Started

**In MARS chat:**

| Example prompt | Result |
|----------------|--------|
| `Write about Kubernetes security best practices` | Researches, drafts full HTML article, asks before publish |
| `publish it` / `looks good, go ahead` | Calls publish after you confirmed the draft |
| `__GW_PUBLISH__` (programmatic) | Autonomous write + publish pipeline |

**Local install and test** (offline):

```bash
pip install -r mars-ghost-writer/requirements.txt
cd mars-ghost-writer
export ALLOW_NET=0
pytest -q
python scripts/smoke_invoke.py
```

Optional live LLM + CMS:

```bash
export HARNESS_INFERENCE_BASE_URL=...
export HARNESS_INFERENCE_MODEL=...
export HARNESS_INFERENCE_API_KEY=...
export BLOG_TYPE=ghost
export BLOG_URL=https://myblog.com
export BLOG_API_KEY=id:secret
export ALLOW_NET=1
```

Full operator copy: `mars-ghost-writer/README.md`.

---

## Pin on MARS when available

1. Set `FRAMEWORK_SUBDIR: mars-ghost-writer` with repo SHA pin
2. Secrets: `HARNESS_INFERENCE_API_KEY`, blog CMS vars
3. Spec stub: `specs/mars-ghost-writer.yaml`
