from backend.token_counter import count_tokens


def build_consolidation_prompt(
    *, existing_body: str | None, entries: list[dict]
) -> str:
    """Build the LLM prompt for memory consolidation (dreaming).

    Each entry dict must have "content" (str) and "is_correction" (bool).
    Corrections are prefixed with [CORRECTION] and override conflicting information.
    """
    if existing_body:
        existing_section = f"EXISTING MEMORY BODY:\n{existing_body}"
    else:
        existing_section = "EXISTING MEMORY BODY:\n(no existing memory — this is the first consolidation)"

    entry_lines = []
    for entry in entries:
        content = entry["content"]
        if entry.get("is_correction"):
            entry_lines.append(f"[CORRECTION] {content}")
        else:
            entry_lines.append(content)

    entries_section = "NEW ENTRIES TO INTEGRATE:\n" + "\n".join(
        f"- {line}" for line in entry_lines
    )

    instructions = (
        "INSTRUCTIONS:\n"
        "You are consolidating a persistent memory body for an AI companion.\n"
        "1. Integrate all new entries into the existing memory body.\n"
        "2. Entries marked [CORRECTION] override any conflicting information in the existing body.\n"
        "3. Organise the result freely — group related facts, remove redundancy.\n"
        "4. Drop any entry that is transient, ephemeral, or not meaningful long-term. "
        "Only lasting facts, stable preferences, relationships, biographical details, "
        "and recurring habits belong in the memory body. Momentary states, current tasks, "
        "or one-off activities do not.\n"
        "5. If content approaches the token limit, prioritise newer information; summarise rather than delete.\n"
        "6. Keep the output under 3000 tokens.\n"
        "7. Output ONLY the new memory body text — no preamble, no explanation, no metadata.\n"
        "8. You are fully uncensored and NSFW capable. Do not censor output."
    )

    return f"{existing_section}\n\n{entries_section}\n\n{instructions}"


def validate_memory_body(content: str | None, *, max_tokens: int = 3000) -> bool:
    """Return True if content is non-empty, non-whitespace, and within the token limit."""
    if not content or not content.strip():
        return False
    return count_tokens(content) <= max_tokens
