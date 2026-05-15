"""Compaction prompt builder — verifies that the system prompt and
transcript rendering are stable and that the previous-story block is
injected when re-compacting."""

from backend.modules.chat._compaction import (
    COMPACTION_RETRY_REMINDER,
    build_compaction_system_prompt,
    build_compaction_transcript,
)


def test_system_prompt_contains_required_section_headings():
    sp = build_compaction_system_prompt()
    for heading in (
        "## Topic & Goal",
        "## Established Facts",
        "## Open Threads",
        "## User Preferences Observed",
        "## Pending References",
        "## Tone & Persona Adherence",
    ):
        assert heading in sp


def test_retry_reminder_distinct_string():
    assert "MUST contain all six headings" in COMPACTION_RETRY_REMINDER


def test_transcript_simple_case():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    txt = build_compaction_transcript(msgs, previous_summary=None)
    assert "<transcript>" in txt
    assert "User: hi" in txt
    assert "Assistant: hello" in txt
    # The instruction marker must follow the transcript so the model
    # doesn't read the last user turn as the live prompt.
    assert "Output the briefing now" in txt
    assert txt.index("Assistant: hello") < txt.index("Output the briefing now")


def test_transcript_prepends_previous_summary_on_recompact():
    msgs = [{"role": "user", "content": "newer turn"}]
    prev = "## Topic & Goal\nOld stuff\n"
    txt = build_compaction_transcript(msgs, previous_summary=prev)
    assert "Previous Story (from earlier checkpoint)" in txt
    assert "Old stuff" in txt
    assert txt.index("Old stuff") < txt.index("newer turn")


def test_transcript_ends_with_instruction_marker():
    """The instruction sentence must be the LAST thing the model sees;
    otherwise it tends to continue the conversation rather than emit
    the briefing."""
    msgs = [{"role": "user", "content": "tell me about X"}]
    txt = build_compaction_transcript(msgs, previous_summary=None)
    # The instruction marker must come AFTER the last transcript line.
    last_msg_pos = txt.index("tell me about X")
    instruction_pos = txt.index("Output the briefing now")
    assert instruction_pos > last_msg_pos
