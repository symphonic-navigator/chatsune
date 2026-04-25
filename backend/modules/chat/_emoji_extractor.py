"""Extract Unicode emoji sequences from a chat message.

Uses the third-party `regex` package because the stdlib `re` does not
support `\\p{Extended_Pictographic}` or other Unicode property classes.
"""
import regex

# An emoji "unit" is one of:
#   - a pair of regional-indicator codepoints (a country flag), matched first
#     because regional indicators are also Extended_Pictographic and would
#     otherwise be consumed one-by-one;
#   - a base pictographic, optionally followed by VS16 (U+FE0F) to force
#     emoji presentation and/or a skin-tone modifier (\p{EMod}), then zero
#     or more ZWJ-joined pictographic continuations (each itself allowed
#     to carry a trailing VS16).
_EMOJI_RE = regex.compile(
    r"(?:\p{Regional_Indicator}\p{Regional_Indicator})"
    r"|"
    r"\p{Extended_Pictographic}️?(?:\p{EMod})?"
    r"(?:‍\p{Extended_Pictographic}️?)*"
)


def extract_emojis(text: str) -> list[str]:
    """Return emojis in order of appearance, preserving skin-tone modifiers
    and ZWJ-joined sequences as single units."""
    return _EMOJI_RE.findall(text)
