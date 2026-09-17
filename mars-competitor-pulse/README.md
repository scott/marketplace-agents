# Competitor Pulse

Watchlist → public-web fetch modules → baseline diff → counterposition brief → ask before notify. LangGraph agent shaped for DigitalOcean MARS (Managed Agents / Harness Runtime).

## Getting started (MARS chat)

Start a chat and name the companies you want to track in plain English — no JSON or presets required.

**Examples**

| What you type | What happens |
|---------------|--------------|
| `Track OpenAI, Anthropic, and Google for SpaceXAI` | Resolves OpenAI, Anthropic, and Google AI with public marketing URLs |
| `Pulse on Cursor and Perplexity` | Tracks Cursor and Perplexity |
| `Track Cursor and alert on Slack` | Tracks Cursor; sets `notify=true` for the approval gate |
| `track fedex` | Sets up a watch on FedEx with best-effort public URLs (LLM when inference is configured) |
| `hi` or `thanks` | Conversational greeting — invites you to name companies (no fixture pulse) |
| `what do you do?` / `how does this work?` | In-character help on tracking, baselines, notify, and v1 limits |

**How intake works**

1. If `competitors` is already in run state (`internal.competitors`), it is kept. Legacy `watchlist` JSON keys in chat still parse.
2. Otherwise the latest chat message is parsed:
   - **Known aliases** (OpenAI, Anthropic, Google/Gemini/DeepMind, Perplexity, Microsoft Copilot, xAI/Grok, Cursor, Meta/Llama, Mistral, Cohere, Amazon Bedrock/Q, Apple Intelligence, …) resolve **offline** to a watchlist with public HTTPS URLs.
   - With **harness inference** configured (`HARNESS_INFERENCE_API_KEY` or `OPENAI_API_KEY`), an LLM pass can extract less common company names and best-effort URLs.
   - An **explicit tracking request** that names no resolvable companies (e.g. `Track FooBar and BazQuux`) returns **blocked** with a prompt to name specific competitors — it does **not** silently fall back to Acme fixtures.
   - **Chat / help** (`hi`, `thanks`, `what do you do?`, `how does this work?`) get a warm, personality-forward reply — no URL fetch, no Acme fixture fallback.
   - **Programmatic invoke** with no chat text (empty `messages`) still uses the fixture watchlist for smoke and tests.
   - **Raw JSON** payloads are parsed silently — they never appear as assistant chat text.

**Defaults from chat**

- `notify=false` unless you mention notify, alert, or Slack.
- `allow_net=true` for NL-derived watchlists (live public pages). Tests and smoke pass `allow_net: false` explicitly.

**Power users (optional)**

- Fenced or raw JSON with `competitors` (or legacy `watchlist`), `notify`, `allow_net`, `channel`
- `{"preset": "spacexai"}` or the `SPACEXAI_PRESET` token for the bundled SpaceXAI competitor set

## What it does

- Loads a competitor watchlist from chat, state, or fixtures
- Gathers site / pricing / changelog / careers snapshots (fixtures offline; optional public HTTP when `ALLOW_NET=1`)
- Diffs against workspace/fixture baseline JSON
- **First run** (no prior baseline for those pages): establishes baseline and summarizes what the pages look like in plain English — not “material changes”
- **Later runs**: short PM-readable bullets with evidence URLs when content actually moved
- Stops for human approval before notify when notify is requested and changes are material

## Chat tone (operator-facing)

Competitor Pulse has a sharp, dry GTM-researcher personality in MARS chat — helpful, not corporate. Greetings and how-to questions get a single warm reply; pulse work stays factual.

The graph speaks through a single `AIMessage`. Chat/help/other: `intake` emits that message and routes to **END** (diag-shaped one-node path — mars-pulse-diag proved MARS does **not** inject `{"watchlist":[]}`; Pulse still did while using a multi-node chat path + `fixtures/watchlist.json`). Pulse paths finish at `report`. Competitor lists live under `internal.competitors` (not in input/output schemas). Fixture files are `fixtures/competitors.json` (legacy filename `watchlist.json` removed). JSON intake still accepts a legacy `"watchlist"` **string key inside chat JSON** on parse only. Never raw JSON or HTML source in chat bubbles.

| Situation | What you see |
|-----------|----------------|
| `hi` / `what do you do?` | Short conversational reply — no pulse run |
| `track fedex` (first time) | Short ack + **First look — baseline established** with human page summaries |
| Quiet re-run | **No changes** since last pulse |
| Material diff | What moved + optional counterposition one-liners |
| Notify | Off by default; set `notify: true` to gate an approval ask |

**Before (bad):** `{"watchlist":[{"name":"FedEx",...}]}` or delta bullets with `<!DOCTYPE HTML…`

**After (good):** “Got it — setting up a watch on **FedEx**. … First look — baseline established. … homepage looks like an error/downtime page — ‘FedEx \| System Downtime’.”

## What it does not (v1)

- Auto-notify or send real Slack/email (act stubs `notify_id` only)
- Competitor logins, signup identity, or scrape behind login
- Churn winback / marketplace / desktop-bot branding
- Presenting Approve when the diff is empty, on first baseline capture, or notify is disabled

## Run flow

```
intake → (chat/help/other → END | pulse → execute_pulse → **ask** → act → report | blocked → report)
```

`execute_pulse` runs plan → gather → analyze → draft internally.

**Ask is skipped** on first-baseline capture, when the diff is empty / non-material (`status: empty`), when `notify` is false (default), or when intake is blocked.

Only `report` appends to `messages[]`. Earlier stages update `stage_summaries` only.

### MARS chat UI sender label

The DO MARS session UI labels assistant bubbles **LangGraph** when the agent spec uses `agent: langgraph` / `template: langgraph` (see `specs/mars-competitor-pulse.yaml`). That label is **not** controlled by this repo's graph code.

What we set from the repo (for any platform that reads it):

| Lever | Value |
|-------|-------|
| `compile(name=…)` | `Competitor Pulse` |
| `langgraph.json` → `graphs.agent.description` | Competitor Pulse tagline |
| `AIMessage.name` on the final reply | `Competitor Pulse` |
| MARS spec `name:` | `mars-competitor-pulse` / `competitor-pulse` |

If the MARS UI chip still reads **LangGraph** after deploy, that is a platform/template default — not something we can override honestly from agent source alone. Assistant display names on LangGraph Agent Server are normally set via the Assistants API (`name` / `description`), which MARS manages outside this repo.

## Human approval

When the graph reaches **ask**, the run pauses until you **Send notify** (`approve`) or **Quiet — keep brief** (`deny`).

| If you… | Resume | The agent will… |
|---------|--------|-----------------|
| **Send notify** | `approve` | Stub-notify in state (`status: notified`, `notify_id`; no real Slack/email in v1) |
| **Quiet — keep brief** | `deny` | Keep brief artifacts; skip notify; finish with status `denied` |

You will see: **Notify about competitor changes?** plus material change count, competitors, highlights, notify draft, and a will-not list.

### Ask body (shape)

```text
Send a pulse notify via {channel}?

Material changes: {delta_count}
Competitors: {comma-separated names with deltas}

Highlights:
{3–7 bullets from deltas}

Counterposition brief: attached in this run (not posted in full unless included below).

Notify draft:
{notify_draft}

Will not: contact competitors, create accounts, or scrape behind login.
```

## Run on DigitalOcean MARS

**Prerequisites**

- DigitalOcean account with Managed Agents / MARS access (Private Preview as applicable)
- This repo public on GitHub (MARS pins a SHA)
- Inference available via harness env (see below)

**Pin**

1. Create or open a MARS agent environment that accepts a LangGraph Agent Server app.
2. Point it at this GitHub repo; pin commit SHA `{sha}`.
3. Ensure root `langgraph.json` is detected (graph export via module-level `.compile(name="CompetitorPulse")`).
4. Set harness inference env (names below). Do not hardcode keys in the repo.
5. Deploy / start the agent server; run one smoke invoke (see Smoke).

See `mars.spec.example.yaml` for `FRAMEWORK_REPO` / `FRAMEWORK_REPO_SHA` placeholders.

**Harness inference env (required)**

| Variable | Purpose |
|----------|---------|
| `HARNESS_INFERENCE_BASE_URL` | OpenAI-compatible base URL |
| `HARNESS_INFERENCE_MODEL`    | Model id |
| `HARNESS_INFERENCE_API_KEY`  | API key |

Fallbacks `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL` are OK if documented, but prefer harness names first.

**Permissions / tools**

- v1 offline path uses `fixtures/competitors.json`, `fixtures/snapshots/`, and `fixtures/baselines/*.json`
- Public HTTP fetch only when `ALLOW_NET=1`; tests/smoke set `ALLOW_NET=0`
- `notify` defaults **off** — records intent in state only; no Action Gateway / Slack required for local proof

## Smoke

**Chat (primary)** — send a HumanMessage in MARS or pass `messages` in invoke input:

```text
Track OpenAI, Anthropic, and Google for SpaceXAI
```

```text
Pulse on Cursor and Perplexity
```

```text
Track Cursor and alert on Slack
```

**First-look path (no ask)** — empty baseline + chat or `user_message`:

```json
{
  "user_message": "track fedex",
  "allow_net": false
}
```

**Fixture path (no chat)** — programmatic invoke without chat text uses Acme/BetaCo fixtures:

```bash
ALLOW_NET=0 python scripts/smoke_invoke.py
```

**Quiet path (no ask)** — pass state with a quiet baseline:

```json
{
  "notify": false,
  "baseline_path": "fixtures/baselines/quiet.json",
  "allow_net": false
}
```

**Power-user JSON** (optional) — explicit competitor list in chat or state:

```json
{
  "competitors": [{"name": "Acme", "urls": {"site": "https://example.com/acme/"}}],
  "notify": true,
  "channel": "slack",
  "allow_net": false
}
```

Legacy `watchlist` key in JSON chat payloads is still accepted.

Expect across paths:

1. Stages through `draft` without side effects.
2. An **ask** interrupt when notify is on and `material == true`; or a clean `empty` / `baseline` report with no ask.
3. After Approve: stub notify evidence (`status: notified`, `notify_id` stub).
4. After Deny: `status: denied` and no notify.

## Local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
export ALLOW_NET=0
# optional live LLM / HTTP:
# export HARNESS_INFERENCE_BASE_URL=...
# export HARNESS_INFERENCE_MODEL=...
# export HARNESS_INFERENCE_API_KEY=...
# export ALLOW_NET=1
pytest -q
python scripts/smoke_invoke.py
```

MARS path stays primary; local is for graph tests. Without an API key and with `ALLOW_NET=0`, the fixture pulse path is fully deterministic.

## License

MIT
