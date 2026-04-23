"""Cryptographic primitives for per-user key infrastructure.

This module wraps the low-level primitives from ``cryptography.hazmat`` with
a small, purpose-built surface: HKDF-based wrap-key derivation, AES-256-GCM
wrap / unwrap of DEK-sized payloads, and HMAC-based deterministic pseudo-salt
derivation for the user-enumeration defence.

All byte quantities are raw ``bytes`` (not base64); callers choose encoding.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


_NONCE_LEN = 12
_TAG_LEN = 16


class AesGcmUnwrapError(Exception):
    """Raised when AES-GCM authentication fails on unwrap."""


def decode_base64url(s: str) -> bytes:
    """``base64.urlsafe_b64decode`` tolerant of missing ``=`` padding.

    The JavaScript ``btoa``-based base64url encoder on the client strips
    trailing padding per RFC 4648 §5, but Python's stdlib decoder requires
    it. This helper re-adds the padding before decoding so callers do not
    need to care about which side produced the string.
    """
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


def derive_wrap_key(input_material: bytes, *, info: bytes, length: int = 32) -> bytes:
    """Derive a symmetric wrap key from input material using HKDF-SHA-256.

    ``info`` must be a stable byte string identifying the purpose, e.g.
    ``b"dek-wrap"``; different purposes must use different ``info`` values
    to prevent cross-context key reuse.
    """
    if not info:
        raise ValueError("info must be non-empty")
    hkdf = HKDF(algorithm=SHA256(), length=length, salt=None, info=info)
    return hkdf.derive(input_material)


def aes_gcm_wrap(key: bytes, plaintext: bytes) -> bytes:
    """Wrap ``plaintext`` with AES-256-GCM. Layout: nonce || ciphertext || tag."""
    if len(key) != 32:
        raise ValueError(f"key must be 32 bytes, got {len(key)}")
    nonce = os.urandom(_NONCE_LEN)
    ct_and_tag = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
    return nonce + ct_and_tag


def aes_gcm_unwrap(key: bytes, blob: bytes) -> bytes:
    """Unwrap ``blob`` produced by :func:`aes_gcm_wrap`.

    Raises :class:`AesGcmUnwrapError` on any authentication failure.
    """
    if len(key) != 32:
        raise ValueError(f"key must be 32 bytes, got {len(key)}")
    if len(blob) < _NONCE_LEN + _TAG_LEN:
        raise AesGcmUnwrapError("blob too short to contain nonce + tag")
    nonce, ct_and_tag = blob[:_NONCE_LEN], blob[_NONCE_LEN:]
    try:
        return AESGCM(key).decrypt(nonce, ct_and_tag, associated_data=None)
    except InvalidTag as exc:
        raise AesGcmUnwrapError("AES-GCM authentication failed") from exc


def pseudo_salt_for_unknown_user(username: str, pepper: bytes) -> bytes:
    """Deterministic 32-byte pseudo-salt for usernames that do not exist.

    Used by ``POST /api/auth/kdf-params`` so responses for unknown users are
    indistinguishable from responses for real users. Stable per username
    (case-insensitive, whitespace-stripped) so repeated probes match.
    """
    if len(pepper) != 32:
        raise ValueError(f"pepper must be 32 bytes, got {len(pepper)}")
    normalised = username.strip().lower().encode("utf-8")
    return hmac.new(pepper, normalised, hashlib.sha256).digest()
