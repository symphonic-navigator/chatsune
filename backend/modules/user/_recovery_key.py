"""Recovery-key generation, formatting, and parsing (Crockford-Base32).

Key format for display and entry: ``XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX``
(8 groups of 4 characters, hyphens for readability). The raw underlying
material is 20 bytes (160 bit), encoded as 32 Crockford-Base32 characters.
Crockford is chosen over standard Base32 because it excludes the visually
ambiguous characters I, L, O, U and accepts ``O``/``I``/``L`` on input as
synonyms for ``0``/``1``/``1`` — friendlier when a user copies the key
from paper or a phone display.
"""

from __future__ import annotations

import os

RECOVERY_KEY_RAW_BYTES = 20
RECOVERY_KEY_DISPLAY_LENGTH = 32 + 7  # 32 chars + 7 hyphens = 39

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford-Base32, no I L O U
_DECODE: dict[str, int] = {c: i for i, c in enumerate(_ALPHABET)}
# Crockford input leniency
for src, dst in {"O": "0", "I": "1", "L": "1"}.items():
    _DECODE[src] = _DECODE[dst]
    _DECODE[src.lower()] = _DECODE[dst]
for c, i in list(_DECODE.items()):
    _DECODE[c.lower()] = i


class InvalidRecoveryKeyError(ValueError):
    """Raised when a recovery key fails to decode."""


def generate_recovery_key() -> str:
    """Generate a freshly random recovery key in display form."""
    raw = os.urandom(RECOVERY_KEY_RAW_BYTES)
    return encode_recovery_key(raw)


def encode_recovery_key(raw: bytes) -> str:
    """Encode 20 bytes as the 39-character display string with hyphens."""
    if len(raw) != RECOVERY_KEY_RAW_BYTES:
        raise InvalidRecoveryKeyError(
            f"raw must be {RECOVERY_KEY_RAW_BYTES} bytes, got {len(raw)}"
        )
    # Convert bytes to a big-endian integer, then repeatedly divmod by 32.
    n = int.from_bytes(raw, "big")
    chars: list[str] = []
    for _ in range(32):
        n, rem = divmod(n, 32)
        chars.append(_ALPHABET[rem])
    encoded = "".join(reversed(chars))
    return "-".join(encoded[i : i + 4] for i in range(0, 32, 4))


def normalise_recovery_key(user_input: str) -> str:
    """Strip whitespace, remove hyphens, uppercase. Result is 32 chars on success."""
    stripped = "".join(ch for ch in user_input if not ch.isspace() and ch != "-")
    return stripped.upper()


def decode_recovery_key(user_input: str) -> bytes:
    """Parse a user-supplied recovery key to its 20 raw bytes.

    Accepts the display form (with hyphens) or the compact form (no hyphens),
    case-insensitive, with Crockford leniency on O/I/L.
    """
    normalised = normalise_recovery_key(user_input)
    if len(normalised) != 32:
        raise InvalidRecoveryKeyError(
            f"recovery key must have 32 significant characters, got {len(normalised)}"
        )
    n = 0
    for ch in normalised:
        try:
            n = n * 32 + _DECODE[ch]
        except KeyError as exc:
            raise InvalidRecoveryKeyError(f"invalid character: {ch!r}") from exc
    return n.to_bytes(RECOVERY_KEY_RAW_BYTES, "big")
