"""Unicode normalisation for PTI trigger phrases and user messages.

Three steps, applied identically to phrases on save and to messages on match:

1. Unicode NFC composition — makes visually identical strings byte-identical.
2. casefold() — Unicode-aware lowercasing (handles ß→ss, Turkish dotted I, etc.).
3. Whitespace collapse — any whitespace class run becomes one ASCII space, trimmed.

The function is idempotent: normalise(normalise(s)) == normalise(s).

NOTE: A TypeScript mirror lives at frontend/src/features/knowledge/normalisePhrase.ts.
The two implementations MUST stay in sync — see INSIGHTS.md.
"""

from __future__ import annotations

import unicodedata


def normalise(s: str) -> str:
    """Normalise a string for PTI matching."""
    s = unicodedata.normalize("NFC", s)
    s = s.casefold()
    # str.split() with no args splits on any Unicode whitespace and drops empties
    s = " ".join(s.split())
    return s
