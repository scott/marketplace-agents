"""Golden checks for Sol PULSE-PERSONA-COPY wiring."""

from __future__ import annotations

from competitor_pulse.persona import (
    NOTIFY_ASK_TITLE,
    PULSE_SYSTEM_PROMPT,
    ask_body,
    brief_prose,
    help_message,
    quiet_message,
    track_plan_message,
    welcome_message,
)


def test_welcome_has_safety_promise_and_starters():
    w = welcome_message()
    wl = w.lower()
    assert "competitor pulse" in wl
    assert "without your ok" in wl or "will not notify" in wl
    assert "Track OpenAI, Anthropic, and Google" in w
    assert "Pulse on Cursor and Perplexity" in w
    assert "Track Cursor and alert on Slack" in w
    assert "—" not in w
    assert " -- " not in w


def test_help_mentions_v1_stub_and_modules():
    h = help_message().lower()
    assert "baseline" in h
    assert "stub" in h or "v1" in h
    assert "pricing" in h and "careers" in h


def test_quiet_is_one_liner_not_status_dump():
    q = quiet_message(["Acme"], ["site"])
    assert "nothing material" in q.lower()
    assert "status:" not in q.lower()
    assert "intake" not in q.lower()


def test_ask_body_question_first_and_stub_honesty():
    body = ask_body(
        channel="slack",
        delta_count=2,
        names=["Acme", "Globex"],
        highlights="- Acme: pricing moved",
        notify_draft="Pulse: 2 material change(s) on Acme, Globex.",
    )
    assert body.startswith("Want me to send this pulse notify via slack?")
    first_line = body.split("\n", 1)[0]
    assert first_line.endswith("?")
    assert "slack" in first_line.lower()
    assert "I will not:" in body
    assert "stub" in body.lower()
    assert "pending_action" not in body
    assert "review site_copy_change" not in body


def test_material_brief_has_no_counter_review_prefix():
    deltas = [
        {
            "competitor": "Acme",
            "module": "pricing",
            "summary": "Pro tier seats dropped",
            "evidence_url": "https://example.com/pricing",
        }
    ]
    brief = brief_prose(first_run=False, deltas=deltas)
    assert "Counter " not in brief
    assert "review site_copy_change" not in brief
    assert "How we might respond" in brief
    assert "homepage / product site" not in brief  # pricing module
    assert "pricing page" in brief
    assert "public web only" in PULSE_SYSTEM_PROMPT.lower() or "Public web only" in PULSE_SYSTEM_PROMPT


def test_conversational_reply_ignores_harness_llm(monkeypatch):
    """Chat path must not llm.invoke — MARS would duplicate greeting in doctl text."""
    monkeypatch.setenv("HARNESS_INFERENCE_API_KEY", "test-key")
    monkeypatch.setenv("HARNESS_INFERENCE_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("HARNESS_INFERENCE_MODEL", "dummy")

    def boom(*_a, **_k):
        raise AssertionError("converse must not call get_llm")

    monkeypatch.setattr("competitor_pulse.llm.get_llm", boom)
    from competitor_pulse.converse import conversational_reply
    from competitor_pulse.persona import welcome_message

    assert conversational_reply("chat", "hi") == welcome_message()


def test_notify_ask_title_sol():
    assert NOTIFY_ASK_TITLE == "Notify about competitor changes?"


def test_track_plan_prose_not_json():
    plan = track_plan_message(["OpenAI", "Anthropic"], notify=False)
    assert "Here's the watch plan:" in plan
    assert "Companies: OpenAI, Anthropic" in plan
    assert "{" not in plan
    assert "Want me to start this watch and run a pulse?" in plan


def test_voice_track_confirm_question():
    plan = track_plan_message(["Tesla"], notify=False)
    lines = [ln.strip() for ln in plan.splitlines() if ln.strip()]
    assert lines[-1].endswith("?")
    assert "watch" in lines[-1].lower() or "pulse" in lines[-1].lower()
