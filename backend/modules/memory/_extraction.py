"""
Content filtering and prompt construction for journal extraction.

strip_technical_content removes pasted code, stacktraces, logs, and raw data
dumps from user messages before they are sent to the extraction LLM. The
goal is to keep human-written context while discarding machine-generated noise.

build_extraction_prompt assembles the full system prompt for the journal
extraction LLM call, including existing memory and journal context.
"""

import re


# ---------------------------------------------------------------------------
# Regex patterns compiled once at module load
# ---------------------------------------------------------------------------

# Fenced code blocks: ```lang ... ``` or ~~~ ... ~~~
_FENCED_CODE = re.compile(r"(`{3,}|~{3,}).*?\1", re.DOTALL)

# Python tracebacks: from "Traceback (most recent call last):" until a blank line
# or end of string.
_PYTHON_TRACEBACK = re.compile(
    r"Traceback \(most recent call last\):.*?(?=\n\s*\n|\Z)",
    re.DOTALL,
)

# Java/Kotlin/Scala-style exception lines:
#   SomeException: message
#   \tat com.example.Foo.bar(Foo.java:42)
_JAVA_EXCEPTION_START = re.compile(
    r"^[\w.$]+(?:Exception|Error)[^\n]*(?:\n\s+at [^\n]+)+",
    re.MULTILINE,
)

# Log lines starting with ISO-like timestamps: 2026-04-06 or 2026-04-06T
_LOG_LINE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\n]*", re.MULTILINE)

# Single-line JSON with multiple keys: { "key": value, "key2": value2 }
# Heuristic: line that starts with { or [ and contains at least two "key": patterns.
_SINGLE_LINE_JSON = re.compile(
    r'^[ \t]*(?:\{|\[).*?"[^"]+"\s*:.*?"[^"]+"\s*:.*$',
    re.MULTILINE,
)

# Indented code blocks: 2+ consecutive lines each starting with 4+ spaces or a tab,
# preceded by a blank line (or start of string) — standard Markdown indented code.
_INDENTED_BLOCK = re.compile(
    r"(?:(?<=\n\n)|(?<=\A))(?:(?:[ ]{4}|\t)[^\n]+\n?)+",
    re.MULTILINE,
)


def strip_technical_content(text: str) -> str:
    """Remove technical raw data from *text*, preserving human-written prose."""
    if not text:
        return text

    # Remove fenced code blocks first (highest priority — they can contain anything)
    text = _FENCED_CODE.sub("", text)

    # Remove Python tracebacks
    text = _PYTHON_TRACEBACK.sub("", text)

    # Remove Java-style exception stacks
    text = _JAVA_EXCEPTION_START.sub("", text)

    # Remove timestamp log lines
    text = _LOG_LINE.sub("", text)

    # Remove single-line JSON/data dumps with multiple keys
    text = _SINGLE_LINE_JSON.sub("", text)

    # Remove indented code blocks (must come after fenced block removal so
    # indented content inside fences is already gone)
    text = _INDENTED_BLOCK.sub("", text)

    # Collapse runs of 3+ blank lines down to two
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_EXTRACTION_INSTRUCTIONS = """\
You are a memory extraction assistant. Your task is to identify facts, preferences, \
and corrections from the user's messages that are worth remembering long-term.

Output a JSON array. Each element must be an object with exactly these fields:
  - "content"      : string — the extracted fact or preference, written as a \
short, self-contained statement
  - "category"     : string — one of: preference, fact, correction, goal, context
  - "is_correction": boolean — true if the message corrects or contradicts \
something already known about the user

Rules:
- Do NOT extract pasted technical content (code, logs, stack traces, raw data). \
  You MAY note what the user is working on if they describe it in plain language.
- Do NOT invent facts. Only extract what is explicitly stated or strongly implied.
- If there is nothing worth extracting, return an empty array: []
- Return ONLY the JSON array — no prose, no markdown fences around it.\
"""


def build_extraction_prompt(
    *,
    memory_body: str | None,
    journal_entries: list[str],
    messages: list[str],
) -> str:
    """Build the system prompt for the journal extraction LLM call.

    Parameters
    ----------
    memory_body:
        The current free-text memory body for this persona, or None if empty.
    journal_entries:
        Existing journal entries (short strings) already stored for this persona.
    messages:
        User messages to analyse for extractable facts.
    """
    parts: list[str] = [_EXTRACTION_INSTRUCTIONS, ""]

    # --- Existing memory context ---
    parts.append("## Existing Memory")
    if memory_body:
        parts.append(memory_body)
    else:
        parts.append("(No existing memory — this persona has none yet.)")
    parts.append("")

    # --- Existing journal entries ---
    parts.append("## Existing Journal Entries")
    if journal_entries:
        for entry in journal_entries:
            parts.append(f"- {entry}")
    else:
        parts.append("(None)")
    parts.append("")

    # --- Messages to process ---
    parts.append("## User Messages to Process")
    for i, msg in enumerate(messages, start=1):
        parts.append(f"[{i}] {msg}")
    parts.append("")

    parts.append(
        "Now extract relevant facts and preferences from the messages above "
        "and return the JSON array as instructed."
    )

    return "\n".join(parts)
