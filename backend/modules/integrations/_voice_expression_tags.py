"""Canonical xAI voice expression tag vocabulary and system-prompt builder.

This file is one half of a two-file source of truth; the other half is
``frontend/src/features/voice/expressionTags.ts``. Any change here must
be mirrored there. See the "xAI Voice Expression Tags" note in
``CLAUDE.md``.
"""

from __future__ import annotations

INLINE_TAGS: list[str] = [
    # Pauses
    "pause", "long-pause", "hum-tune",
    # Laughter, crying & exclamations
    "laugh", "chuckle", "giggle", "cry", "whoop",
    # Mouth sounds
    "tsk", "tongue-click", "lip-smack",
    # Breathing
    "breath", "inhale", "exhale", "sigh", "gasp",
]

WRAPPING_TAGS: list[str] = [
    # Volume & intensity
    "soft", "whisper", "loud", "build-intensity", "decrease-intensity",
    # Pitch & speed
    "higher-pitch", "lower-pitch", "slow", "fast",
    # Vocal style
    "sing-song", "singing", "laugh-speak", "emphasis",
]


def build_system_prompt_extension() -> str:
    inline_lines = "\n".join(
        f"- `[{tag}]` — {_describe_inline(tag)}" for tag in INLINE_TAGS
    )
    wrapping_lines = "\n".join(
        f"- `<{tag}>…</{tag}>` — {_describe_wrapping(tag)}" for tag in WRAPPING_TAGS
    )
    return (
        '<integrations name="xai_voice">\n'
        "## Voice Expression\n\n"
        "Your speech is synthesised by xAI's voice engine, which understands "
        "two kinds of expression markup in the text you write. Used with "
        "restraint, these make your voice sound alive; overused, they make "
        "it exhausting to listen to.\n\n"
        "### Syntax\n\n"
        "- Inline tags in square brackets trigger a discrete sound or "
        "pause: `[laugh]`, `[breath]`, `[pause]`.\n"
        "- Inline tags may carry a short qualifier word in the same "
        "brackets: `[soft laugh]`, `[exhale sharply]`, `[quick breath]` "
        "are all valid.\n"
        "- Wrapping tags in angle brackets modulate the voice across the "
        "text they enclose: `<whisper>a secret</whisper>`.\n"
        "- Wrapping tags may nest: `<soft><emphasis>word</emphasis></soft>`.\n\n"
        "### Inline tags\n\n"
        f"{inline_lines}\n\n"
        "### Wrapping tags\n\n"
        f"{wrapping_lines}\n\n"
        "### Dosage recipe\n\n"
        "Typically 0–2 markups per message. Not every sentence. "
        "Use a wrapping tag for genuine emphasis, a pause to let a "
        "punchline land, a breath when it would feel natural to take one. "
        "Speech sounds natural when markup is rare.\n\n"
        "### Narrator-mode interaction\n\n"
        "When you write dialogue in straight or curly double quotes, the "
        "dialogue is synthesised in a different voice from the narration. "
        "A wrapping tag placed inside the quotes applies only to the "
        "dialogue voice. A wrapping tag placed around quoted dialogue and "
        "surrounding narration applies to both voices. Prefer to keep a "
        "wrapping tag either fully inside or fully outside a quote; "
        "avoid starting a wrap in narration and ending it inside dialogue "
        "(or vice versa).\n"
        "</integrations>"
    )


def _describe_inline(tag: str) -> str:
    table = {
        "pause": "a short silence",
        "long-pause": "a longer deliberate silence",
        "hum-tune": "a brief hummed tune",
        "laugh": "a full laugh",
        "chuckle": "a quiet chuckle",
        "giggle": "a playful giggle",
        "cry": "a sob or cry",
        "whoop": "a whoop of excitement",
        "tsk": "a disapproving tsk",
        "tongue-click": "a tongue click",
        "lip-smack": "a lip smack",
        "breath": "an audible breath",
        "inhale": "an inward breath",
        "exhale": "an outward breath",
        "sigh": "a sigh",
        "gasp": "a sharp gasp",
    }
    return table[tag]


def _describe_wrapping(tag: str) -> str:
    table = {
        "soft": "soften the delivery",
        "whisper": "whisper",
        "loud": "raise the volume",
        "build-intensity": "build intensity across the wrapped text",
        "decrease-intensity": "fade intensity across the wrapped text",
        "higher-pitch": "raise the pitch",
        "lower-pitch": "lower the pitch",
        "slow": "slow the pace",
        "fast": "speed up the pace",
        "sing-song": "sing-song intonation",
        "singing": "sing the wrapped text",
        "laugh-speak": "speak through laughter",
        "emphasis": "emphasise the wrapped text",
    }
    return table[tag]
