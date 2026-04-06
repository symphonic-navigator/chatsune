from backend.token_counter import count_tokens


def assemble_memory_context(
    *,
    memory_body: str | None,
    committed_entries: list[dict],
    uncommitted_entries: list[dict],
    max_tokens: int = 6000,
) -> str | None:
    """Build the <usermemory> XML block for system prompt injection.

    Returns None when there is no memory content at all.
    Respects the token budget — journal entries are dropped when the budget is exhausted.
    """
    if not memory_body and not committed_entries and not uncommitted_entries:
        return None

    remaining = max_tokens
    sections: list[str] = []

    if memory_body:
        body_block = f"<memory-body>\n{memory_body}\n</memory-body>"
        remaining -= count_tokens(body_block)
        sections.append(body_block)

    journal_lines: list[str] = []

    for entry in committed_entries:
        line = f"- [committed] {entry['content']}"
        cost = count_tokens(line)
        if cost <= remaining:
            remaining -= cost
            journal_lines.append(line)

    for entry in uncommitted_entries:
        line = f"- [pending] {entry['content']}"
        cost = count_tokens(line)
        if cost <= remaining:
            remaining -= cost
            journal_lines.append(line)

    if journal_lines:
        journal_block = "<journal>\n" + "\n".join(journal_lines) + "\n</journal>"
        sections.append(journal_block)

    inner = "\n".join(sections)
    return f'<usermemory priority="normal">\n{inner}\n</usermemory>'
