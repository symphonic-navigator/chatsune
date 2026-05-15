"""Pure helpers for chat compaction (no IO, no LLM calls).

The job handler in backend/jobs/handlers/_chat_compaction.py composes
these functions with the repository, the LLM client, and the event bus.
"""

from __future__ import annotations


_MIN_TAIL_MESSAGES = 12      # 6 turns
_TAIL_TOKEN_FRACTION = 0.20  # 20 % of model context


def determine_tail_start_index(
    messages: list[dict], *, model_context: int,
) -> int:
    """Return the index of the first message that must stay in the tail.

    Walks newest → oldest, accumulating ``token_count``. The tail extends
    until BOTH the 6-turn floor (12 messages) AND the 20% token rule are
    satisfied — i.e. whichever rule yields the LARGER tail wins.
    """
    if not messages:
        return 0

    total = len(messages)
    token_budget = int(model_context * _TAIL_TOKEN_FRACTION)

    tail_tokens = 0
    chosen_idx = total
    for i in range(total - 1, -1, -1):
        tail_tokens += int(messages[i].get("token_count") or 0)
        tail_messages = total - i
        if tail_messages >= _MIN_TAIL_MESSAGES and tail_tokens >= token_budget:
            chosen_idx = i
            break
        chosen_idx = i

    return max(0, chosen_idx)


def select_source_range(
    messages: list[dict],
    *,
    tail_start_index: int,
    prev_tail_start_id: str | None,
) -> tuple[list[dict], list[dict]]:
    """Split messages into source range (to be compacted) and tail.

    When ``prev_tail_start_id`` is provided, the source begins at that
    message (re-compact case: only the messages added since the previous
    checkpoint are condensed; the previous compact-markdown is folded in
    as Previous Story by the prompt builder).

    Raises ``ValueError`` when ``prev_tail_start_id`` is set but no
    matching message exists in ``messages`` — that points to a data
    integrity problem the caller must handle (the previous checkpoint
    referenced a message that has since been deleted).
    """
    tail = messages[tail_start_index:]
    if prev_tail_start_id is None:
        source = messages[:tail_start_index]
    else:
        try:
            start = next(
                i for i, m in enumerate(messages)
                if m["_id"] == prev_tail_start_id
            )
        except StopIteration:
            raise ValueError(
                f"prev_tail_start_id {prev_tail_start_id!r} not found in messages"
            )
        source = messages[start:tail_start_index]
    return source, tail


def sanitise_source(source: list[dict]) -> list[dict]:
    """Drop tool-role messages and empty-content assistant messages.
    Everything else (user, text-bearing assistant, any other role) is
    passed through. The compact-prompt builder later renders only roles
    it recognises, so non-standard roles are harmless here.
    """
    cleaned: list[dict] = []
    for m in source:
        role = m.get("role")
        if role == "tool":
            continue
        if role == "assistant" and not (m.get("content") or "").strip():
            continue
        cleaned.append(m)
    return cleaned


import re

# Each entry is a regex that matches the section heading in any of the
# common renderings a model might emit: ``## Topic & Goal``, ``# Topic
# and Goal``, ``**Topic & Goal**``, with or without trailing colon, any
# case. We match the *keywords* rather than the literal heading string,
# which is robust to GPT-4o-style paraphrasing while still rejecting
# garbage output that misses entire sections.
_REQUIRED_SECTION_PATTERNS = (
    ("topic.+goal", "Topic & Goal"),
    ("established.+facts?", "Established Facts"),
    ("open.+threads?", "Open Threads"),
    ("(user.+preferences?|preferences? observed)", "User Preferences Observed"),
    ("pending.+references?", "Pending References"),
    ("(tone.+persona|persona.+adherence)", "Tone & Persona Adherence"),
)


class CompactionValidationError(Exception):
    """Raised when a compact-markdown output fails structural checks."""


def validate_compact_markdown(markdown: str) -> None:
    """Raise CompactionValidationError if markdown is not a valid briefing.

    Checks: non-empty, all six required section topics present (matched
    case-insensitively and tolerant of heading-style variations such as
    ``# Topic and Goal`` or ``**Topic & Goal:**``), code fences balanced.
    The model's prose may otherwise vary freely.
    """
    text = (markdown or "").strip()
    if not text:
        raise CompactionValidationError("compact markdown was empty")

    missing: list[str] = []
    for pattern, label in _REQUIRED_SECTION_PATTERNS:
        if not re.search(pattern, text, flags=re.IGNORECASE):
            missing.append(label)
    if missing:
        raise CompactionValidationError(
            f"compact markdown missing required sections: {missing}",
        )

    fence_count = sum(1 for line in text.splitlines() if line.strip().startswith("```"))
    if fence_count % 2 != 0:
        raise CompactionValidationError("compact markdown has unbalanced code fence")


COMPACTION_SYSTEM_PROMPT_TOKENS = 380   # rough estimate, used by pre-flight
COMPACTION_MAX_OUTPUT_TOKENS = 2000
COMPACTION_SAFETY_MARGIN = 1000


COMPACTION_RETRY_REMINDER = (
    "\n\nIMPORTANT: The previous attempt was missing required sections. "
    "Output MUST contain all six headings exactly as specified, in the "
    "order shown."
)


def build_compaction_system_prompt() -> str:
    """Verbatim system prompt for compaction jobs. See spec §6.4."""
    return (
        "You are a conversation-compaction assistant. Below is a transcript "
        "of a conversation between a user and an AI assistant. Your job is "
        "to extract a structured briefing that allows another AI to "
        "seamlessly continue this conversation in a new context window.\n\n"
        "Output rules:\n"
        "- Output Markdown only. No preamble, no \"I have summarised\", no "
        "meta-commentary.\n"
        "- Use the exact section headings shown below, in order.\n"
        "- Be terse but complete. Aim for 5–10 % of the original token count.\n"
        "- Preserve the user's language preferences, name, and any "
        "established facts about them.\n"
        "- Quote critical user phrasings verbatim if they carry intent "
        "(e.g. preferences, decisions).\n"
        "- Do not invent information. If a section has no content, write "
        "\"_(none)_\".\n\n"
        "Required sections:\n\n"
        "## Topic & Goal\n"
        "What is this conversation about? What is the user trying to achieve?\n\n"
        "## Established Facts\n"
        "Concrete facts, decisions, names, numbers, conclusions reached. Bullet list.\n\n"
        "## Open Threads\n"
        "Questions left unanswered, things the user said they would come back to.\n\n"
        "## User Preferences Observed\n"
        "Communication style, expertise level, language preferences, "
        "anything that should shape how the next AI responds.\n\n"
        "## Pending References\n"
        "Files, URLs, artefacts, tools that the user mentioned and that "
        "the next assistant should know about. Do not paste their content "
        "— just reference them by name.\n\n"
        "## Tone & Persona Adherence\n"
        "One sentence on how the persona has been speaking (formal/informal, etc.).\n"
    )


def build_compaction_transcript(
    source_messages: list[dict],
    *,
    previous_summary: str | None,
) -> str:
    """Render the user-prompt content for a compaction call.

    On re-compact, prepends the previous checkpoint's markdown as a
    'Previous Story' block so no information is lost across compactions.
    """
    parts: list[str] = []
    if previous_summary:
        parts.append("## Previous Story (from earlier checkpoint)\n\n"
                     f"{previous_summary.strip()}\n\n"
                     "---\n\n"
                     "## Conversation since the previous checkpoint\n")
    for m in source_messages:
        role = (m.get("role") or "user").capitalize()
        content = (m.get("content") or "").strip()
        if content:
            parts.append(f"{role}: {content}")
    return "\n".join(parts)
