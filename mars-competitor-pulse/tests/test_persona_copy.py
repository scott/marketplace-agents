"""Golden checks for Sol PULSE-PERSONA-COPY wiring."""

from __future__ import annotations

from competitor_pulse.persona import (
    PULSE_SYSTEM_PROMPT,
    ask_body,
    brief_prose,
    help_message,
    quiet_message,
    welcome_message,
)


def test_welcome_has_safety_promise_and_starters():
    w = welcome_message().lower()
    assert "competitor pulse" in w
    assert "without your ok" in w or "will not notify" in w
    assert "openai" in w and "cursor" in w
    assert "slack" in w


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
