import re

_RESERVED_TAG_NAMES = [
    "systeminstructions", "system-instructions", "system_instructions",
    "modelinstructions", "model-instructions", "model_instructions",
    "you",
    "userinfo", "user-info", "user_info",
    "usermemory", "user-memory", "user_memory",
]

# Match opening tags (with any attributes), closing tags, and self-closing tags
_TAG_PATTERN = re.compile(
    r"</?(?:" + "|".join(re.escape(t) for t in _RESERVED_TAG_NAMES) + r")(?:\s[^>]*)?>|"
    r"<(?:" + "|".join(re.escape(t) for t in _RESERVED_TAG_NAMES) + r")\s*/>",
    re.IGNORECASE,
)


def sanitise(text: str | None) -> str:
    """Strip all reserved XML tags from user-controlled content.

    Removes opening, closing, and self-closing variants of reserved tags.
    The content between tags is preserved — only the tags themselves are removed.
    """
    if not text:
        return ""
    return _TAG_PATTERN.sub("", text)
