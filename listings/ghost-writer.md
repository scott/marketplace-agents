# Ghost Writer — research, draft, publish (with your OK)

**For** content operators who want an AI blog author that researches the web, writes full HTML drafts, and publishes to Ghost or WordPress — without surprise posts.

**Job-to-be-done:** Brainstorm → research → full draft in chat → **publish only after you confirm** (or autonomous publish via `__GW_PUBLISH__`).

**Why MARS / LangGraph:** Fourth agent in the marketplace-agents monorepo — compiled graph keyed **`agent`**, pin with `FRAMEWORK_SUBDIR=mars-ghost-writer`.

---

## What you get

- Chat path: brainstorm, research, draft, explicit publish gate
- Autonomous publish sentinel (`__GW_PUBLISH__` / `GW_RUN_MODE=publish`)
- Ghost + WordPress clients, optional feature images
- Offline pytest (`ALLOW_NET=0`); harness LLM env with OpenAI fallback

## What you don't

- Standalone FastAPI/TUI/Docker from upstream repo (MARS graph only here)
- Publish without confirmation in chat mode
- Live web search in offline tests (mocked)

---

## Getting Started

```bash
pip install -r mars-ghost-writer/requirements.txt
cd mars-ghost-writer
export ALLOW_NET=0
pytest -q
python scripts/smoke_invoke.py
```

Operator README: `mars-ghost-writer/README.md`. Spec: `specs/mars-ghost-writer.yaml`.
