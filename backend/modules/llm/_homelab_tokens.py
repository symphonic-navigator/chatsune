"""Token generation, hashing and hint extraction for Community Provisioning.

High-entropy random tokens (256 bits) are stored as SHA-256 hashes.
Per OWASP, a single SHA-256 pass is sufficient for high-entropy tokens;
slow hashes (argon2id) are unnecessary and prohibitively expensive on
the per-request validation path.
"""

from __future__ import annotations

import hashlib
import secrets

HOST_KEY_PREFIX = "cshost_"
API_KEY_PREFIX = "csapi_"
HOMELAB_ID_LENGTH = 11  # token_urlsafe(8) → 11 chars


def generate_host_key() -> str:
    return f"{HOST_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def generate_api_key() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def generate_homelab_id() -> str:
    return secrets.token_urlsafe(8)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hint_for(token: str) -> str:
    return token[-4:] if len(token) >= 4 else token
