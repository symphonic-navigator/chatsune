"""Extract Unicode emoji sequences from a chat message.

Uses the third-party `regex` package because the stdlib `re` does not
support `\\p{Extended_Pictographic}` or other Unicode property classes.
"""
import regex

# An emoji "unit" is a base pictographic optionally followed by:
#   - one skin-tone modifier (\p{EMod}), or
#   - one or more ZWJ-joined pictographic continuations.
_EMOJI_RE = regex.compile(
    r"\p{Extended_Pictographic}(?:\p{EMod}|‍\p{Extended_Pictographic})*"
)


def extract_emojis(text: str) -> list[str]:
    """Return emojis in order of appearance, preserving skin-tone modifiers
    and ZWJ-joined sequences as single units."""
    return _EMOJI_RE.findall(text)
