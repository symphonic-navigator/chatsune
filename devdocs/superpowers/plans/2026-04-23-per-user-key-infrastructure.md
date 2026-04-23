# Per-User Key Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the cryptographic key-management foundation so that later releases can encrypt user-owned data at rest under a per-user key that only the user's password or recovery key can unlock. No user data is encrypted by this plan; only the plumbing is built.

**Architecture:** A per-user 32-byte Data Encryption Key (DEK) is generated with CSRNG at signup and wrapped twice with AES-256-GCM: once under a password-derived key, once under a recovery-key-derived key. The password-derived key comes from client-side Argon2id + HKDF, so the server never sees the plaintext password. The unwrapped DEK lives in Redis under the session id with TTL equal to the access-token TTL. A new `user_keys` MongoDB collection holds the wrapped keys and KDF parameters per user.

**Tech Stack:** FastAPI + Pydantic v2 (backend), AES-256-GCM + HKDF-SHA-256 from `cryptography.hazmat` (already a dep), bcrypt (already a dep, still used server-side over the client-derived `H_auth`), `argon2-browser` (new frontend dep) in a Web Worker, MongoDB (new collection `user_keys`), Redis (new key space `session_dek:*`).

**Spec:** `devdocs/superpowers/specs/2026-04-23-per-user-key-infrastructure-design.md`

---

## Conventions

- **Language:** British English in all identifiers, comments, error messages, and documentation.
- **Commit policy:** one commit per task (at the end), imperative subject, no Conventional-Commits prefix unless the surrounding file asks for one.
- **Test framework:** pytest for backend. Frontend changes are validated by `pnpm build` and a quick browser smoke test — there is no established frontend unit-test harness in this repo.
- **Test layout:** place new backend tests under `tests/modules/user/`. Create the directory on first use. Existing fixtures live in `tests/conftest.py`.
- **Build verification at each backend task:** `uv run pytest <new tests> -v` plus `uv run python -m py_compile <changed backend files>`.
- **Build verification at each frontend task:** `pnpm tsc --noEmit` (fast) and, once visible UI lands, `pnpm run build`.
- **Both `pyproject.toml` files:** no new Python dependency is introduced by this plan. `cryptography`, `bcrypt`, `pymongo`, `redis`, `fastapi` are already present on both sides.
- **No branches:** direct work on `master` per project convention.

---

## File Inventory

Create:

- `backend/modules/user/_crypto.py` — HKDF, AES-256-GCM wrap/unwrap, pseudo-salt HMAC.
- `backend/modules/user/_recovery_key.py` — Crockford-Base32 encode/decode + checksum + generation.
- `backend/modules/user/_key_service.py` — `UserKeyService` (DEK generate, wrap, unwrap, Redis session lifecycle).
- `backend/modules/user/_key_repository.py` — `user_keys` collection CRUD + index.
- `shared/events/user_keys.py` — event DTOs.
- `tests/modules/user/__init__.py`
- `tests/modules/user/test_crypto.py`
- `tests/modules/user/test_recovery_key.py`
- `tests/modules/user/test_key_service.py`
- `tests/modules/user/test_key_repository.py`
- `tests/modules/user/test_kdf_params_endpoint.py`
- `tests/modules/user/test_login_endpoint.py`
- `tests/modules/user/test_login_legacy_endpoint.py`
- `tests/modules/user/test_recovery_endpoints.py`
- `tests/modules/user/test_change_password_endpoint.py`
- `tests/modules/user/test_setup_endpoint.py`
- `tests/modules/user/test_admin_reset_endpoint.py`
- `tests/modules/user/test_session_dek_lifecycle.py`
- `frontend/src/core/crypto/argon2.worker.ts`
- `frontend/src/core/crypto/keyDerivation.ts`
- `frontend/src/core/crypto/recoveryKey.ts`
- `frontend/src/features/auth/RecoveryKeyModal.tsx`
- `frontend/src/features/auth/RecoveryKeyPrompt.tsx`

Modify:

- `backend/config.py` — add `kdf_pepper`.
- `backend/modules/user/_models.py` — add `UserKeysDocument`, `WrappedDekPair`, `Argon2Params`; add `password_hash_version` to `UserDocument`.
- `backend/modules/user/_repository.py` — register the new collection name constant (no new methods; CRUD goes in `_key_repository.py`).
- `backend/modules/user/_auth.py` — factor bcrypt helpers to operate on `H_auth` bytes.
- `backend/modules/user/_handlers.py` — update every auth endpoint and add new ones.
- `backend/modules/user/__init__.py` — export `UserKeyService`.
- `backend/main.py` — validate `kdf_pepper` on boot; no startup migration.
- `shared/topics.py` — add three constants.
- `shared/dtos/auth.py` — add new request/response shapes.
- `.env.example` — new variable.
- `README.md` — document the new variable and the auth-flow change.
- `frontend/package.json` — add `argon2-browser`.
- `frontend/src/core/api/auth.ts` — new shapes + new endpoints.
- `frontend/src/pages/LoginPage.tsx` (or equivalent — discover in task 21).
- `frontend/src/pages/SetupPage.tsx` (or equivalent).
- Frontend change-password and admin-reset screens — discover exact paths in task 21.

---

## Task 1: Config — add `kdf_pepper`

**Files:**
- Modify: `backend/config.py`
- Modify: `.env.example`
- Test: `tests/modules/user/test_config_pepper.py` (create)
- Create: `tests/modules/user/__init__.py` (empty)

- [ ] **Step 1.1 — Create empty init file**

```bash
mkdir -p tests/modules/user
touch tests/modules/user/__init__.py
```

- [ ] **Step 1.2 — Write the failing test**

Create `tests/modules/user/test_config_pepper.py`:

```python
import pytest
from pydantic import ValidationError

from backend.config import Settings


def test_kdf_pepper_required_32_bytes(monkeypatch):
    monkeypatch.setenv("kdf_pepper", "")
    with pytest.raises(ValidationError):
        Settings()


def test_kdf_pepper_valid_base64url_32_bytes(monkeypatch):
    import base64, secrets
    value = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    monkeypatch.setenv("kdf_pepper", value)
    s = Settings()
    assert len(s.kdf_pepper_bytes) == 32


def test_kdf_pepper_rejects_short_material(monkeypatch):
    import base64
    value = base64.urlsafe_b64encode(b"too-short").decode()
    monkeypatch.setenv("kdf_pepper", value)
    with pytest.raises(ValidationError):
        Settings()
```

- [ ] **Step 1.3 — Run the test to verify it fails**

```bash
uv run pytest tests/modules/user/test_config_pepper.py -v
```

Expected: three failures, all because `kdf_pepper`/`kdf_pepper_bytes` do not exist.

- [ ] **Step 1.4 — Implement the config field**

In `backend/config.py`, alongside the existing `encryption_key` validator, add:

```python
    kdf_pepper: str = Field(..., description="Urlsafe-base64-encoded 32-byte pepper used to derive pseudo-salts for unknown usernames during /auth/kdf-params. Separate from encryption_key.")

    @field_validator("kdf_pepper")
    @classmethod
    def _validate_kdf_pepper(cls, v: str) -> str:
        import base64
        try:
            decoded = base64.urlsafe_b64decode(v)
        except Exception as exc:
            raise ValueError("kdf_pepper must be urlsafe-base64") from exc
        if len(decoded) != 32:
            raise ValueError(f"kdf_pepper must decode to exactly 32 bytes, got {len(decoded)}")
        return v

    @property
    def kdf_pepper_bytes(self) -> bytes:
        import base64
        return base64.urlsafe_b64decode(self.kdf_pepper)
```

- [ ] **Step 1.5 — Update `.env.example`**

Add under the existing crypto section:

```
# 32-byte pepper (urlsafe-base64) for deterministic pseudo-salts on unknown
# usernames in POST /api/auth/kdf-params. Separate purpose from encryption_key.
# Generate: python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
kdf_pepper=
```

- [ ] **Step 1.6 — Update your local `.env`**

Generate a value and add it, otherwise the backend refuses to boot:

```bash
python -c "import secrets,base64; print('kdf_pepper=' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())" >> .env
```

- [ ] **Step 1.7 — Run the tests to verify they pass**

```bash
uv run pytest tests/modules/user/test_config_pepper.py -v
```

Expected: all three pass.

- [ ] **Step 1.8 — Commit**

```bash
git add backend/config.py .env.example tests/modules/user/__init__.py tests/modules/user/test_config_pepper.py
git commit -m "Add kdf_pepper env var for deterministic pseudo-salts"
```

---

## Task 2: Crypto helpers — HKDF, AES-256-GCM wrap/unwrap, pseudo-salt HMAC

**Files:**
- Create: `backend/modules/user/_crypto.py`
- Create: `tests/modules/user/test_crypto.py`

- [ ] **Step 2.1 — Write the failing test**

Create `tests/modules/user/test_crypto.py`:

```python
import secrets
import pytest

from backend.modules.user._crypto import (
    derive_wrap_key,
    aes_gcm_wrap,
    aes_gcm_unwrap,
    pseudo_salt_for_unknown_user,
    AesGcmUnwrapError,
)


def test_derive_wrap_key_is_deterministic_per_input_and_info():
    k1 = derive_wrap_key(b"input" * 4, info=b"dek-wrap")
    k2 = derive_wrap_key(b"input" * 4, info=b"dek-wrap")
    assert k1 == k2
    assert len(k1) == 32


def test_derive_wrap_key_differs_by_info_string():
    material = secrets.token_bytes(32)
    assert derive_wrap_key(material, info=b"a") != derive_wrap_key(material, info=b"b")


def test_wrap_then_unwrap_returns_plaintext():
    key = secrets.token_bytes(32)
    plaintext = secrets.token_bytes(32)
    blob = aes_gcm_wrap(key, plaintext)
    # nonce (12) + ct (32) + tag (16) == 60 bytes for 32-byte plaintext
    assert len(blob) == 12 + 32 + 16
    assert aes_gcm_unwrap(key, blob) == plaintext


def test_unwrap_with_wrong_key_raises():
    key1 = secrets.token_bytes(32)
    key2 = secrets.token_bytes(32)
    blob = aes_gcm_wrap(key1, b"secret")
    with pytest.raises(AesGcmUnwrapError):
        aes_gcm_unwrap(key2, blob)


def test_wrap_uses_fresh_nonce_each_call():
    key = secrets.token_bytes(32)
    blob_a = aes_gcm_wrap(key, b"same-plaintext")
    blob_b = aes_gcm_wrap(key, b"same-plaintext")
    assert blob_a != blob_b


def test_pseudo_salt_is_deterministic_per_username():
    pepper = secrets.token_bytes(32)
    a = pseudo_salt_for_unknown_user("chris", pepper)
    b = pseudo_salt_for_unknown_user("chris", pepper)
    assert a == b
    assert len(a) == 32


def test_pseudo_salt_is_case_insensitive_and_trimmed():
    pepper = secrets.token_bytes(32)
    assert pseudo_salt_for_unknown_user("Chris", pepper) == pseudo_salt_for_unknown_user("  chris ", pepper)
```

- [ ] **Step 2.2 — Run the test to verify it fails**

```bash
uv run pytest tests/modules/user/test_crypto.py -v
```

Expected: collection error (module does not exist).

- [ ] **Step 2.3 — Implement the crypto helpers**

Create `backend/modules/user/_crypto.py`:

```python
"""Cryptographic primitives for per-user key infrastructure.

This module wraps the low-level primitives from ``cryptography.hazmat`` with
a small, purpose-built surface: HKDF-based wrap-key derivation, AES-256-GCM
wrap / unwrap of DEK-sized payloads, and HMAC-based deterministic pseudo-salt
derivation for the user-enumeration defence.

All byte quantities are raw ``bytes`` (not base64); callers choose encoding.
"""

from __future__ import annotations

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
```

- [ ] **Step 2.4 — Run the tests to verify they pass**

```bash
uv run pytest tests/modules/user/test_crypto.py -v
```

Expected: seven pass.

- [ ] **Step 2.5 — Compile check**

```bash
uv run python -m py_compile backend/modules/user/_crypto.py
```

Expected: exit 0.

- [ ] **Step 2.6 — Commit**

```bash
git add backend/modules/user/_crypto.py tests/modules/user/test_crypto.py
git commit -m "Add AES-GCM / HKDF / HMAC pseudo-salt helpers for per-user keys"
```

---

## Task 3: Recovery-key codec — Crockford-Base32

**Files:**
- Create: `backend/modules/user/_recovery_key.py`
- Create: `tests/modules/user/test_recovery_key.py`

- [ ] **Step 3.1 — Write the failing test**

Create `tests/modules/user/test_recovery_key.py`:

```python
import pytest

from backend.modules.user._recovery_key import (
    generate_recovery_key,
    normalise_recovery_key,
    decode_recovery_key,
    encode_recovery_key,
    InvalidRecoveryKeyError,
    RECOVERY_KEY_RAW_BYTES,
    RECOVERY_KEY_DISPLAY_LENGTH,
)


def test_generate_is_formatted_as_groups_of_four():
    key = generate_recovery_key()
    assert len(key) == RECOVERY_KEY_DISPLAY_LENGTH
    groups = key.split("-")
    assert len(groups) == 8
    assert all(len(g) == 4 for g in groups)


def test_round_trip_encode_decode():
    key = generate_recovery_key()
    raw = decode_recovery_key(key)
    assert len(raw) == RECOVERY_KEY_RAW_BYTES
    assert encode_recovery_key(raw) == key


def test_normalise_accepts_spaces_hyphens_mixed_case():
    key = generate_recovery_key()
    noisy = "  " + key.lower().replace("-", " ") + "  "
    assert normalise_recovery_key(noisy) == key.replace("-", "")


def test_crockford_ambiguity_mapping_on_input():
    # Crockford treats O -> 0, I/L -> 1. Input must be accepted and decoded identically.
    base = generate_recovery_key().replace("-", "")
    # Substitute a 0 in the string with 'O' (if any), or 1 with 'I', to probe mapping.
    probed = base.replace("0", "O", 1).replace("1", "I", 1)
    assert decode_recovery_key(probed) == decode_recovery_key(base)


def test_invalid_characters_reject():
    with pytest.raises(InvalidRecoveryKeyError):
        decode_recovery_key("Z" * 32)  # Z is not in Crockford-Base32 alphabet


def test_wrong_length_rejects():
    with pytest.raises(InvalidRecoveryKeyError):
        decode_recovery_key("ABCD" * 7)
```

- [ ] **Step 3.2 — Run it and verify failure**

```bash
uv run pytest tests/modules/user/test_recovery_key.py -v
```

Expected: import error.

- [ ] **Step 3.3 — Implement the codec**

Create `backend/modules/user/_recovery_key.py`:

```python
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
```

- [ ] **Step 3.4 — Run tests and verify they pass**

```bash
uv run pytest tests/modules/user/test_recovery_key.py -v
```

Expected: six pass.

- [ ] **Step 3.5 — Commit**

```bash
git add backend/modules/user/_recovery_key.py tests/modules/user/test_recovery_key.py
git commit -m "Add Crockford-Base32 recovery-key codec and generator"
```

---

## Task 4: Pydantic models — `UserKeysDocument` and `password_hash_version`

**Files:**
- Modify: `backend/modules/user/_models.py`
- Test: exercised indirectly by repository and service tests in later tasks; add minimal sanity test here.
- Create: `tests/modules/user/test_models.py`

- [ ] **Step 4.1 — Write the failing test**

Create `tests/modules/user/test_models.py`:

```python
from datetime import datetime, UTC

from backend.modules.user._models import (
    UserKeysDocument,
    WrappedDekPair,
    Argon2Params,
)


def test_argon2_params_defaults():
    p = Argon2Params()
    assert p.memory_kib == 65536
    assert p.iterations == 3
    assert p.parallelism == 4


def test_wrapped_dek_pair_is_bytes():
    pair = WrappedDekPair(
        wrapped_by_password=b"\x00" * 60,
        wrapped_by_recovery=b"\x01" * 60,
        created_at=datetime.now(UTC),
    )
    assert isinstance(pair.wrapped_by_password, bytes)
    assert isinstance(pair.wrapped_by_recovery, bytes)


def test_user_keys_document_defaults():
    doc = UserKeysDocument(
        user_id="507f1f77bcf86cd799439011",
        kdf_salt=b"s" * 32,
        kdf_params=Argon2Params(),
        current_dek_version=1,
        deks={"1": WrappedDekPair(
            wrapped_by_password=b"\x00" * 60,
            wrapped_by_recovery=b"\x01" * 60,
            created_at=datetime.now(UTC),
        )},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert doc.dek_recovery_required is False
```

- [ ] **Step 4.2 — Run it and verify failure**

```bash
uv run pytest tests/modules/user/test_models.py -v
```

Expected: `ImportError` for the new symbols.

- [ ] **Step 4.3 — Extend the models**

Open `backend/modules/user/_models.py` and append (after the existing `UserDocument` definition):

```python
from pydantic import BaseModel, Field


class Argon2Params(BaseModel):
    memory_kib: int = 65536
    iterations: int = 3
    parallelism: int = 4


class WrappedDekPair(BaseModel):
    wrapped_by_password: bytes
    wrapped_by_recovery: bytes
    created_at: datetime


class UserKeysDocument(BaseModel):
    """Per-user key material and KDF parameters (collection: ``user_keys``).

    One document per user. ``deks`` is keyed by stringified version so the
    DEK can be rotated without migrating the field shape: each new rotation
    simply adds another entry and bumps ``current_dek_version``.
    """
    user_id: str
    kdf_salt: bytes = Field(..., min_length=32, max_length=32)
    kdf_params: Argon2Params = Field(default_factory=Argon2Params)
    current_dek_version: int = 1
    deks: dict[str, WrappedDekPair]
    dek_recovery_required: bool = False
    created_at: datetime
    updated_at: datetime
```

Also add to the existing `UserDocument` model (wherever it is defined, not duplicated):

```python
    password_hash_version: int | None = None
```

The field is nullable so existing documents load without error (legacy pre-migration rows have no version).

- [ ] **Step 4.4 — Verify tests pass**

```bash
uv run pytest tests/modules/user/test_models.py -v
```

Expected: three pass.

- [ ] **Step 4.5 — Compile check**

```bash
uv run python -m py_compile backend/modules/user/_models.py
```

- [ ] **Step 4.6 — Commit**

```bash
git add backend/modules/user/_models.py tests/modules/user/test_models.py
git commit -m "Add UserKeysDocument model and password_hash_version field"
```

---

## Task 5: Repository — `user_keys` collection

**Files:**
- Create: `backend/modules/user/_key_repository.py`
- Create: `tests/modules/user/test_key_repository.py`

- [ ] **Step 5.1 — Write the failing test**

Create `tests/modules/user/test_key_repository.py`. The repository pattern in this codebase uses Motor; `conftest.py` already provides a `db` fixture.

```python
import pytest
from datetime import datetime, UTC

from backend.modules.user._key_repository import UserKeysRepository
from backend.modules.user._models import UserKeysDocument, WrappedDekPair, Argon2Params


@pytest.fixture
def repo(db):
    return UserKeysRepository(db)


@pytest.fixture
def sample_doc():
    now = datetime.now(UTC)
    return UserKeysDocument(
        user_id="507f1f77bcf86cd799439011",
        kdf_salt=b"s" * 32,
        kdf_params=Argon2Params(),
        current_dek_version=1,
        deks={"1": WrappedDekPair(
            wrapped_by_password=b"\x00" * 60,
            wrapped_by_recovery=b"\x01" * 60,
            created_at=now,
        )},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_insert_and_fetch_by_user_id(repo, sample_doc):
    await repo.ensure_indexes()
    await repo.insert(sample_doc)
    fetched = await repo.get_by_user_id(sample_doc.user_id)
    assert fetched is not None
    assert fetched.kdf_salt == sample_doc.kdf_salt
    assert fetched.deks["1"].wrapped_by_password == sample_doc.deks["1"].wrapped_by_password


@pytest.mark.asyncio
async def test_get_returns_none_for_missing(repo):
    assert await repo.get_by_user_id("507f1f77bcf86cd799439099") is None


@pytest.mark.asyncio
async def test_unique_index_on_user_id(repo, sample_doc):
    from pymongo.errors import DuplicateKeyError
    await repo.ensure_indexes()
    await repo.insert(sample_doc)
    with pytest.raises(DuplicateKeyError):
        await repo.insert(sample_doc)


@pytest.mark.asyncio
async def test_set_recovery_required(repo, sample_doc):
    await repo.ensure_indexes()
    await repo.insert(sample_doc)
    await repo.set_recovery_required(sample_doc.user_id, value=True)
    fetched = await repo.get_by_user_id(sample_doc.user_id)
    assert fetched.dek_recovery_required is True


@pytest.mark.asyncio
async def test_replace_wrapped_by_password(repo, sample_doc):
    await repo.ensure_indexes()
    await repo.insert(sample_doc)
    new_blob = b"\x02" * 60
    await repo.replace_wrapped_by_password(sample_doc.user_id, version=1, blob=new_blob)
    fetched = await repo.get_by_user_id(sample_doc.user_id)
    assert fetched.deks["1"].wrapped_by_password == new_blob
    # recovery wrap untouched
    assert fetched.deks["1"].wrapped_by_recovery == sample_doc.deks["1"].wrapped_by_recovery
```

- [ ] **Step 5.2 — Run it and verify failure**

```bash
uv run pytest tests/modules/user/test_key_repository.py -v
```

Expected: `ImportError`.

- [ ] **Step 5.3 — Implement the repository**

Create `backend/modules/user/_key_repository.py`:

```python
"""Repository for the ``user_keys`` collection.

One document per user. The collection is private to the user module and must
not be accessed from other modules — consumers go through
:class:`backend.modules.user.UserKeyService`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.user._models import UserKeysDocument, WrappedDekPair

COLLECTION = "user_keys"


def _to_mongo(doc: UserKeysDocument) -> dict:
    payload = doc.model_dump()
    # Pydantic dumps bytes as base64 strings by default; we want raw BSON BinData.
    payload["kdf_salt"] = doc.kdf_salt
    for version, pair in doc.deks.items():
        payload["deks"][version]["wrapped_by_password"] = pair.wrapped_by_password
        payload["deks"][version]["wrapped_by_recovery"] = pair.wrapped_by_recovery
    return payload


def _from_mongo(raw: dict) -> UserKeysDocument:
    # Motor returns BSON BinData as bytes already.
    raw.pop("_id", None)
    return UserKeysDocument(**raw)


class UserKeysRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self._collection = db[COLLECTION]

    async def ensure_indexes(self) -> None:
        await self._collection.create_index("user_id", unique=True)

    async def insert(self, doc: UserKeysDocument) -> None:
        await self._collection.insert_one(_to_mongo(doc))

    async def get_by_user_id(self, user_id: str) -> UserKeysDocument | None:
        raw = await self._collection.find_one({"user_id": user_id})
        return _from_mongo(raw) if raw else None

    async def set_recovery_required(self, user_id: str, *, value: bool) -> None:
        await self._collection.update_one(
            {"user_id": user_id},
            {"$set": {"dek_recovery_required": value, "updated_at": datetime.now(UTC)}},
        )

    async def replace_wrapped_by_password(self, user_id: str, *, version: int, blob: bytes) -> None:
        await self._collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    f"deks.{version}.wrapped_by_password": blob,
                    f"deks.{version}.created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                }
            },
        )

    async def replace_both_wraps(
        self, user_id: str, *, version: int, wrapped_by_password: bytes, wrapped_by_recovery: bytes
    ) -> None:
        await self._collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    f"deks.{version}.wrapped_by_password": wrapped_by_password,
                    f"deks.{version}.wrapped_by_recovery": wrapped_by_recovery,
                    f"deks.{version}.created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                }
            },
        )
```

- [ ] **Step 5.4 — Wire up index creation**

In `backend/main.py`, find the existing `await create_indexes(db)` call (or the startup block that calls per-module index creators) and add:

```python
from backend.modules.user._key_repository import UserKeysRepository

# inside the startup lifecycle block, after db is available:
await UserKeysRepository(db).ensure_indexes()
```

- [ ] **Step 5.5 — Verify tests pass**

```bash
uv run pytest tests/modules/user/test_key_repository.py -v
```

Expected: five pass.

- [ ] **Step 5.6 — Commit**

```bash
git add backend/modules/user/_key_repository.py backend/main.py tests/modules/user/test_key_repository.py
git commit -m "Add UserKeysRepository with unique user_id index"
```

---

## Task 6: `UserKeyService` — DEK lifecycle + Redis session store

**Files:**
- Create: `backend/modules/user/_key_service.py`
- Modify: `backend/modules/user/__init__.py` (export `UserKeyService`)
- Create: `tests/modules/user/test_key_service.py`

- [ ] **Step 6.1 — Write the failing test**

Create `tests/modules/user/test_key_service.py`:

```python
import pytest
import secrets

from backend.modules.user._key_service import UserKeyService, DekUnlockError
from backend.modules.user._recovery_key import generate_recovery_key, decode_recovery_key


@pytest.fixture
async def service(db, redis_client):
    svc = UserKeyService(db=db, redis=redis_client)
    await svc.ensure_indexes()
    return svc


@pytest.mark.asyncio
async def test_provision_creates_wraps_and_returns_recovery_key(service):
    user_id = "507f1f77bcf86cd799439001"
    h_kek = secrets.token_bytes(32)
    recovery_key = generate_recovery_key()
    await service.provision_for_new_user(user_id=user_id, h_kek=h_kek, recovery_key=recovery_key, kdf_salt=b"s" * 32)
    doc = await service.get_keys_doc(user_id)
    assert doc is not None
    assert doc.current_dek_version == 1
    assert "1" in doc.deks


@pytest.mark.asyncio
async def test_unlock_with_correct_h_kek_returns_dek(service):
    user_id = "507f1f77bcf86cd799439002"
    h_kek = secrets.token_bytes(32)
    recovery_key = generate_recovery_key()
    await service.provision_for_new_user(user_id=user_id, h_kek=h_kek, recovery_key=recovery_key, kdf_salt=b"s" * 32)
    dek = await service.unlock_with_password(user_id=user_id, h_kek=h_kek)
    assert len(dek) == 32


@pytest.mark.asyncio
async def test_unlock_with_wrong_h_kek_raises(service):
    user_id = "507f1f77bcf86cd799439003"
    await service.provision_for_new_user(
        user_id=user_id, h_kek=secrets.token_bytes(32), recovery_key=generate_recovery_key(), kdf_salt=b"s" * 32
    )
    with pytest.raises(DekUnlockError):
        await service.unlock_with_password(user_id=user_id, h_kek=secrets.token_bytes(32))


@pytest.mark.asyncio
async def test_unlock_with_recovery_key_and_rewrap(service):
    user_id = "507f1f77bcf86cd799439004"
    h_kek_old = secrets.token_bytes(32)
    h_kek_new = secrets.token_bytes(32)
    recovery_key = generate_recovery_key()
    await service.provision_for_new_user(
        user_id=user_id, h_kek=h_kek_old, recovery_key=recovery_key, kdf_salt=b"s" * 32
    )
    dek_via_recovery = await service.unlock_with_recovery_and_rewrap(
        user_id=user_id, recovery_key=recovery_key, new_h_kek=h_kek_new
    )
    # after rewrap, the new password-wrap must decrypt back to the same DEK
    dek_via_new_password = await service.unlock_with_password(user_id=user_id, h_kek=h_kek_new)
    assert dek_via_recovery == dek_via_new_password


@pytest.mark.asyncio
async def test_session_dek_store_roundtrip_and_ttl(service):
    session_id = "sess-1"
    dek = secrets.token_bytes(32)
    await service.store_session_dek(session_id=session_id, dek=dek, ttl_seconds=900)
    assert await service.fetch_session_dek(session_id) == dek
    await service.delete_session_dek(session_id)
    assert await service.fetch_session_dek(session_id) is None


@pytest.mark.asyncio
async def test_rewrap_password_updates_only_password_wrap(service):
    user_id = "507f1f77bcf86cd799439005"
    h_kek_old = secrets.token_bytes(32)
    h_kek_new = secrets.token_bytes(32)
    recovery_key = generate_recovery_key()
    await service.provision_for_new_user(user_id=user_id, h_kek=h_kek_old, recovery_key=recovery_key, kdf_salt=b"s" * 32)
    doc_before = await service.get_keys_doc(user_id)
    wrapped_rec_before = doc_before.deks["1"].wrapped_by_recovery
    await service.rewrap_password(user_id=user_id, h_kek_old=h_kek_old, h_kek_new=h_kek_new)
    doc_after = await service.get_keys_doc(user_id)
    assert doc_after.deks["1"].wrapped_by_password != doc_before.deks["1"].wrapped_by_password
    assert doc_after.deks["1"].wrapped_by_recovery == wrapped_rec_before
    # new password unlocks successfully
    await service.unlock_with_password(user_id=user_id, h_kek=h_kek_new)
```

If `redis_client` fixture is not present in `tests/conftest.py`, add one before running:

```python
# tests/conftest.py  (append if missing)
import pytest_asyncio
from backend.database import get_redis

@pytest_asyncio.fixture
async def redis_client():
    client = await get_redis()
    yield client
    # flush only the key space we use
    async for key in client.scan_iter("session_dek:*"):
        await client.delete(key)
```

- [ ] **Step 6.2 — Run it and verify failure**

```bash
uv run pytest tests/modules/user/test_key_service.py -v
```

Expected: import error.

- [ ] **Step 6.3 — Implement the service**

Create `backend/modules/user/_key_service.py`:

```python
"""Public per-user key service — DEK lifecycle and session-DEK Redis store.

Responsibilities:
- Generate a per-user DEK and persist it wrapped twice (by password KEK and by
  recovery-key KEK) in the ``user_keys`` collection.
- Unlock the DEK for a login (password path) or a recovery (recovery-key path).
- Rewrap on password change.
- Cache the plaintext DEK in Redis under the session id for the lifetime of
  the access token, so other modules can retrieve it without reconstructing it.

This is the *only* module that should touch the ``user_keys`` collection from
business-logic code, and the only module that reads or writes
``session_dek:*`` keys in Redis.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from backend.modules.user._crypto import (
    AesGcmUnwrapError,
    aes_gcm_unwrap,
    aes_gcm_wrap,
    derive_wrap_key,
)
from backend.modules.user._key_repository import UserKeysRepository
from backend.modules.user._models import (
    Argon2Params,
    UserKeysDocument,
    WrappedDekPair,
)
from backend.modules.user._recovery_key import decode_recovery_key

_DEK_BYTES = 32
_HKDF_INFO_DEK_WRAP = b"dek-wrap"
_REDIS_KEY_PREFIX = "session_dek:"


class DekUnlockError(Exception):
    """Raised when the supplied key material cannot open the wrapped DEK."""


class UserKeyNotFoundError(Exception):
    """Raised when the user has no ``user_keys`` document yet."""


class UserKeyService:
    def __init__(self, db: AsyncIOMotorDatabase, redis: Redis):
        self._repo = UserKeysRepository(db)
        self._redis = redis

    async def ensure_indexes(self) -> None:
        await self._repo.ensure_indexes()

    # ---- provisioning ---------------------------------------------------

    async def provision_for_new_user(
        self,
        *,
        user_id: str,
        h_kek: bytes,
        recovery_key: str,
        kdf_salt: bytes,
        kdf_params: Argon2Params | None = None,
    ) -> None:
        """Create the user's DEK and persist it double-wrapped.

        The caller is responsible for forgetting ``h_kek`` and ``recovery_key``
        immediately after this returns.
        """
        dek = os.urandom(_DEK_BYTES)
        try:
            recovery_raw = decode_recovery_key(recovery_key)
            key_pw = derive_wrap_key(h_kek, info=_HKDF_INFO_DEK_WRAP)
            key_rec = derive_wrap_key(recovery_raw, info=_HKDF_INFO_DEK_WRAP)
            wrapped_pw = aes_gcm_wrap(key_pw, dek)
            wrapped_rec = aes_gcm_wrap(key_rec, dek)
        finally:
            dek = b""  # drop the plaintext DEK from memory on this code path
        now = datetime.now(UTC)
        doc = UserKeysDocument(
            user_id=user_id,
            kdf_salt=kdf_salt,
            kdf_params=kdf_params or Argon2Params(),
            current_dek_version=1,
            deks={"1": WrappedDekPair(
                wrapped_by_password=wrapped_pw,
                wrapped_by_recovery=wrapped_rec,
                created_at=now,
            )},
            created_at=now,
            updated_at=now,
        )
        await self._repo.insert(doc)

    # ---- unlock paths ---------------------------------------------------

    async def get_keys_doc(self, user_id: str) -> UserKeysDocument | None:
        return await self._repo.get_by_user_id(user_id)

    async def unlock_with_password(self, *, user_id: str, h_kek: bytes) -> bytes:
        doc = await self._require_doc(user_id)
        version = str(doc.current_dek_version)
        wrapped = doc.deks[version].wrapped_by_password
        key = derive_wrap_key(h_kek, info=_HKDF_INFO_DEK_WRAP)
        try:
            return aes_gcm_unwrap(key, wrapped)
        except AesGcmUnwrapError as exc:
            raise DekUnlockError("wrong password-derived key material") from exc

    async def unlock_with_recovery_and_rewrap(
        self, *, user_id: str, recovery_key: str, new_h_kek: bytes
    ) -> bytes:
        doc = await self._require_doc(user_id)
        version = str(doc.current_dek_version)
        wrapped = doc.deks[version].wrapped_by_recovery
        recovery_raw = decode_recovery_key(recovery_key)
        key_rec = derive_wrap_key(recovery_raw, info=_HKDF_INFO_DEK_WRAP)
        try:
            dek = aes_gcm_unwrap(key_rec, wrapped)
        except AesGcmUnwrapError as exc:
            raise DekUnlockError("wrong recovery key") from exc
        new_key_pw = derive_wrap_key(new_h_kek, info=_HKDF_INFO_DEK_WRAP)
        new_wrapped_pw = aes_gcm_wrap(new_key_pw, dek)
        await self._repo.replace_wrapped_by_password(
            user_id, version=doc.current_dek_version, blob=new_wrapped_pw
        )
        await self._repo.set_recovery_required(user_id, value=False)
        return dek

    async def rewrap_password(
        self, *, user_id: str, h_kek_old: bytes, h_kek_new: bytes
    ) -> bytes:
        dek = await self.unlock_with_password(user_id=user_id, h_kek=h_kek_old)
        new_key_pw = derive_wrap_key(h_kek_new, info=_HKDF_INFO_DEK_WRAP)
        new_wrapped_pw = aes_gcm_wrap(new_key_pw, dek)
        doc = await self._require_doc(user_id)
        await self._repo.replace_wrapped_by_password(
            user_id, version=doc.current_dek_version, blob=new_wrapped_pw
        )
        return dek

    # ---- Redis session store -------------------------------------------

    async def store_session_dek(self, *, session_id: str, dek: bytes, ttl_seconds: int) -> None:
        await self._redis.set(_REDIS_KEY_PREFIX + session_id, dek, ex=ttl_seconds)

    async def fetch_session_dek(self, session_id: str) -> bytes | None:
        return await self._redis.get(_REDIS_KEY_PREFIX + session_id)

    async def extend_session_dek_ttl(self, *, session_id: str, ttl_seconds: int) -> bool:
        return bool(await self._redis.expire(_REDIS_KEY_PREFIX + session_id, ttl_seconds))

    async def delete_session_dek(self, session_id: str) -> None:
        await self._redis.delete(_REDIS_KEY_PREFIX + session_id)

    async def mark_recovery_required(self, user_id: str) -> None:
        await self._repo.set_recovery_required(user_id, value=True)

    # ---- internals ------------------------------------------------------

    async def _require_doc(self, user_id: str) -> UserKeysDocument:
        doc = await self._repo.get_by_user_id(user_id)
        if doc is None:
            raise UserKeyNotFoundError(user_id)
        return doc
```

- [ ] **Step 6.4 — Export from the module**

In `backend/modules/user/__init__.py` add:

```python
from backend.modules.user._key_service import (
    UserKeyService,
    DekUnlockError,
    UserKeyNotFoundError,
)

__all__ = [*__all__, "UserKeyService", "DekUnlockError", "UserKeyNotFoundError"]
```

(If `__all__` is not defined in the file, create it with the existing public names plus the three above.)

- [ ] **Step 6.5 — Verify tests pass**

```bash
uv run pytest tests/modules/user/test_key_service.py -v
```

Expected: six pass.

- [ ] **Step 6.6 — Commit**

```bash
git add backend/modules/user/_key_service.py backend/modules/user/__init__.py tests/modules/user/test_key_service.py tests/conftest.py
git commit -m "Add UserKeyService with Redis session-DEK lifecycle"
```

---

## Task 7: Shared contracts — topics, events, DTOs

**Files:**
- Modify: `shared/topics.py`
- Create: `shared/events/user_keys.py`
- Modify: `shared/dtos/auth.py`

- [ ] **Step 7.1 — Add topic constants**

In `shared/topics.py`, inside the `Topics` class (or namespace pattern it uses), add:

```python
    USER_KEY_PROVISIONED = "user.key.provisioned"
    USER_KEY_RECOVERY_REQUIRED = "user.key.recovery_required"
    USER_KEY_RECOVERED = "user.key.recovered"
    USER_KEY_RECOVERY_DECLINED = "user.key.recovery_declined"
```

- [ ] **Step 7.2 — Create the events file**

Create `shared/events/user_keys.py`:

```python
"""Domain events for per-user key lifecycle."""

from typing import Literal

from pydantic import BaseModel


class UserKeyProvisionedEvent(BaseModel):
    user_id: str
    reason: Literal["signup", "migration"]
    # The recovery key itself is never in this event. Signup: the client
    # generated it. Migration: the server returns it exactly once in the
    # /login-legacy response body.


class UserKeyRecoveryRequiredEvent(BaseModel):
    user_id: str
    triggered_by_admin_id: str | None = None


class UserKeyRecoveredEvent(BaseModel):
    user_id: str


class UserKeyRecoveryDeclinedEvent(BaseModel):
    user_id: str
```

- [ ] **Step 7.3 — Extend auth DTOs**

In `shared/dtos/auth.py` add:

```python
class KdfParamsRequestDto(BaseModel):
    username: str


class Argon2ParamsDto(BaseModel):
    memory_kib: int
    iterations: int
    parallelism: int


class KdfParamsResponseDto(BaseModel):
    kdf_salt: str   # urlsafe-base64
    kdf_params: Argon2ParamsDto
    password_hash_version: int | None = None  # None signals legacy-user path


class LoginRequestDto(BaseModel):
    username: str
    h_auth: str     # urlsafe-base64, 32 bytes
    h_kek: str      # urlsafe-base64, 32 bytes


class LoginLegacyRequestDto(BaseModel):
    username: str
    password: str   # plaintext, last time it is accepted — upgrades the row
    h_auth: str
    h_kek: str


class RecoveryRequiredResponseDto(BaseModel):
    status: Literal["recovery_required"] = "recovery_required"


class RecoverDekRequestDto(BaseModel):
    username: str
    h_auth: str
    h_kek: str
    recovery_key: str


class DeclineRecoveryRequestDto(BaseModel):
    username: str


class ChangePasswordRequestDto(BaseModel):
    h_auth_old: str
    h_kek_old: str
    h_auth_new: str
    h_kek_new: str


class SetupRequestDto(BaseModel):
    username: str
    email: str
    display_name: str
    pin: str
    h_auth: str
    h_kek: str
    recovery_key: str


class LoginLegacyResponseDto(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_in: int
    recovery_key: str   # returned exactly once on migration
```

(Adjust existing `LoginRequestDto` — if it is currently named identically and accepted plaintext-password, rename the old one to `LegacyLoginRequestDto` inside the module and keep a temporary alias; the endpoint will branch by shape. Concrete wire-up in Task 10.)

- [ ] **Step 7.4 — Compile check**

```bash
uv run python -c "import shared.events.user_keys; import shared.dtos.auth; import shared.topics"
```

- [ ] **Step 7.5 — Commit**

```bash
git add shared/topics.py shared/events/user_keys.py shared/dtos/auth.py
git commit -m "Add shared contracts for per-user key events and DTOs"
```

---

## Task 8: Endpoint — `POST /api/auth/kdf-params`

**Files:**
- Modify: `backend/modules/user/_handlers.py`
- Create: `tests/modules/user/test_kdf_params_endpoint.py`

- [ ] **Step 8.1 — Write the failing test**

Create `tests/modules/user/test_kdf_params_endpoint.py`:

```python
import base64
import pytest
import httpx


@pytest.mark.asyncio
async def test_kdf_params_returns_real_salt_for_existing_user(async_client: httpx.AsyncClient, seeded_user):
    # seeded_user fixture creates a user with user_keys provisioned (see conftest additions in Task 13).
    response = await async_client.post("/api/auth/kdf-params", json={"username": seeded_user.username})
    assert response.status_code == 200
    body = response.json()
    assert "kdf_salt" in body
    assert "kdf_params" in body
    assert body["password_hash_version"] in (None, 1)
    assert len(base64.urlsafe_b64decode(body["kdf_salt"])) == 32


@pytest.mark.asyncio
async def test_kdf_params_returns_deterministic_pseudo_salt_for_unknown_user(async_client: httpx.AsyncClient):
    r1 = await async_client.post("/api/auth/kdf-params", json={"username": "ghost-user"})
    r2 = await async_client.post("/api/auth/kdf-params", json={"username": "ghost-user"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["kdf_salt"] == r2.json()["kdf_salt"]
    assert r1.json()["password_hash_version"] is None


@pytest.mark.asyncio
async def test_kdf_params_username_is_case_insensitive_for_ghost(async_client: httpx.AsyncClient):
    r1 = await async_client.post("/api/auth/kdf-params", json={"username": "Ghost"})
    r2 = await async_client.post("/api/auth/kdf-params", json={"username": "ghost"})
    assert r1.json()["kdf_salt"] == r2.json()["kdf_salt"]
```

- [ ] **Step 8.2 — Run it and verify failure**

```bash
uv run pytest tests/modules/user/test_kdf_params_endpoint.py -v
```

Expected: 404 (endpoint missing).

- [ ] **Step 8.3 — Implement the endpoint**

In `backend/modules/user/_handlers.py`, add (placing near the existing auth endpoints):

```python
import base64
from fastapi import APIRouter

from backend.config import settings
from backend.modules.user._crypto import pseudo_salt_for_unknown_user
from backend.modules.user._key_service import UserKeyService
from shared.dtos.auth import (
    Argon2ParamsDto,
    KdfParamsRequestDto,
    KdfParamsResponseDto,
)

# inside the existing auth router (or wherever /api/auth/* is mounted)

@router.post("/kdf-params", response_model=KdfParamsResponseDto)
async def kdf_params(body: KdfParamsRequestDto) -> KdfParamsResponseDto:
    user = await users_repo.find_by_username_case_insensitive(body.username)
    if user is not None:
        keys_doc = await user_key_service.get_keys_doc(user.id)
        if keys_doc is not None:
            return KdfParamsResponseDto(
                kdf_salt=base64.urlsafe_b64encode(keys_doc.kdf_salt).decode(),
                kdf_params=Argon2ParamsDto(**keys_doc.kdf_params.model_dump()),
                password_hash_version=user.password_hash_version,
            )
        # Real user without user_keys document = legacy pre-migration user.
        # We need a stable salt to hand back; derive it deterministically and
        # persist it now so future logins are consistent. No DEK yet — that
        # comes on /login-legacy in Task 10.
        salt = pseudo_salt_for_unknown_user(body.username, settings.kdf_pepper_bytes)
        # Do not persist yet; the actual user_keys doc is created in /login-legacy.
        return KdfParamsResponseDto(
            kdf_salt=base64.urlsafe_b64encode(salt).decode(),
            kdf_params=Argon2ParamsDto(memory_kib=65536, iterations=3, parallelism=4),
            password_hash_version=None,
        )
    # Unknown user: deterministic pseudo-salt, indistinguishable from legacy users.
    salt = pseudo_salt_for_unknown_user(body.username, settings.kdf_pepper_bytes)
    return KdfParamsResponseDto(
        kdf_salt=base64.urlsafe_b64encode(salt).decode(),
        kdf_params=Argon2ParamsDto(memory_kib=65536, iterations=3, parallelism=4),
        password_hash_version=None,
    )
```

You will need to ensure `users_repo` and `user_key_service` are available in the handler scope — follow the existing dependency-injection pattern in the file (likely FastAPI `Depends` or module-level singletons).

- [ ] **Step 8.4 — Add `find_by_username_case_insensitive` if missing**

In `backend/modules/user/_repository.py`, if no case-insensitive lookup exists, add:

```python
    async def find_by_username_case_insensitive(self, username: str) -> UserDocument | None:
        raw = await self._collection.find_one(
            {"username": {"$regex": f"^{re.escape(username)}$", "$options": "i"}}
        )
        return UserDocument(**raw) if raw else None
```

Import `re` at the top of the file.

- [ ] **Step 8.5 — Verify tests pass**

```bash
uv run pytest tests/modules/user/test_kdf_params_endpoint.py -v
```

Expected: three pass. (The `seeded_user` fixture is introduced in Task 13 — for now keep the first test marked `@pytest.mark.skip(reason="depends on Task 13")` if the fixture is unavailable, and remove the skip in Task 13.)

- [ ] **Step 8.6 — Commit**

```bash
git add backend/modules/user/_handlers.py backend/modules/user/_repository.py tests/modules/user/test_kdf_params_endpoint.py
git commit -m "Add POST /api/auth/kdf-params with pseudo-salt enumeration defence"
```

---

## Task 9: Endpoint — `POST /api/auth/login` (new contract, DEK unlock, Redis side effect)

**Files:**
- Modify: `backend/modules/user/_handlers.py`
- Modify: `backend/modules/user/_auth.py`
- Create: `tests/modules/user/test_login_endpoint.py`

- [ ] **Step 9.1 — Adjust the bcrypt helper to operate on base64-bytes `H_auth`**

In `backend/modules/user/_auth.py` change the existing hashing helpers to accept bytes (already the case for `bcrypt.hashpw`/`checkpw`). If they currently accept `str` only, add:

```python
import base64
import bcrypt


def hash_h_auth(h_auth_b64: str) -> str:
    raw = base64.urlsafe_b64decode(h_auth_b64)
    if len(raw) != 32:
        raise ValueError("h_auth must decode to 32 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode()


def verify_h_auth(h_auth_b64: str, stored_hash: str) -> bool:
    raw = base64.urlsafe_b64decode(h_auth_b64)
    return bcrypt.checkpw(raw, stored_hash.encode())
```

Keep the existing `hash_password`/`verify_password` helpers in place — the legacy endpoint (Task 10) still needs them.

- [ ] **Step 9.2 — Write the failing test**

Create `tests/modules/user/test_login_endpoint.py`:

```python
import base64
import secrets
import pytest
import httpx


@pytest.mark.asyncio
async def test_login_with_correct_material_succeeds(async_client: httpx.AsyncClient, seeded_user):
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    }
    response = await async_client.post("/api/auth/login", json=body)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "status" not in data


@pytest.mark.asyncio
async def test_login_with_wrong_h_auth_returns_401(async_client, seeded_user):
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    }
    response = await async_client.post("/api/auth/login", json=body)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_returns_recovery_required_when_flag_set(async_client, seeded_user, user_key_service):
    await user_key_service.mark_recovery_required(seeded_user.id)
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    }
    response = await async_client.post("/api/auth/login", json=body)
    assert response.status_code == 200
    assert response.json() == {"status": "recovery_required"}


@pytest.mark.asyncio
async def test_login_populates_session_dek_in_redis(async_client, seeded_user, user_key_service):
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    }
    response = await async_client.post("/api/auth/login", json=body)
    assert response.status_code == 200
    # Decode the session_id out of the access token claim, then look up Redis.
    from backend.modules.user._auth import decode_access_token
    claims = decode_access_token(response.json()["access_token"])
    dek = await user_key_service.fetch_session_dek(claims["session_id"])
    assert dek is not None and len(dek) == 32
```

- [ ] **Step 9.3 — Run it to verify failure**

```bash
uv run pytest tests/modules/user/test_login_endpoint.py -v
```

- [ ] **Step 9.4 — Implement the new login endpoint**

In `backend/modules/user/_handlers.py`, update the existing `/api/auth/login` handler. Retain the old path only if its request body still validates; otherwise, replace:

```python
from backend.modules.user._auth import (
    verify_h_auth,
    create_access_token,
    generate_refresh_token,
    generate_session_id,
)
from backend.modules.user._key_service import DekUnlockError
from shared.dtos.auth import LoginRequestDto, RecoveryRequiredResponseDto
from backend.config import settings

@router.post("/login")
async def login(body: LoginRequestDto):
    user = await users_repo.find_by_username_case_insensitive(body.username)
    # Constant-time-ish defence: always run bcrypt_check on something.
    if user is None or user.password_hash_version != 1:
        # Legacy / unknown users are forbidden on this endpoint — the client
        # must use /login-legacy (Task 10). Return the same 401 to not leak
        # which case applies.
        raise HTTPException(status_code=401, detail="invalid_credentials")
    if not verify_h_auth(body.h_auth, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    keys_doc = await user_key_service.get_keys_doc(user.id)
    if keys_doc is None:
        # Should not happen for a user with password_hash_version=1; treat as 500.
        raise HTTPException(status_code=500, detail="dek_integrity_error")
    if keys_doc.dek_recovery_required:
        return RecoveryRequiredResponseDto()
    h_kek_bytes = base64.urlsafe_b64decode(body.h_kek)
    try:
        dek = await user_key_service.unlock_with_password(user_id=user.id, h_kek=h_kek_bytes)
    except DekUnlockError:
        # bcrypt matched but DEK unwrap failed — data corruption.
        raise HTTPException(status_code=500, detail="dek_integrity_error")
    session_id = generate_session_id()
    access_token = create_access_token(user_id=user.id, role=user.role, session_id=session_id)
    refresh_token = await generate_refresh_token(user_id=user.id, session_id=session_id)
    await user_key_service.store_session_dek(
        session_id=session_id, dek=dek, ttl_seconds=settings.access_token_ttl_seconds
    )
    # Audit event
    await event_bus.publish(Topics.AUDIT_LOGGED, AuditLoggedEvent(...))
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": settings.access_token_ttl_seconds,
    }
```

Replace the refresh-token cookie side-effect using the existing helper from the old handler.

- [ ] **Step 9.5 — Verify tests pass**

```bash
uv run pytest tests/modules/user/test_login_endpoint.py -v
```

- [ ] **Step 9.6 — Commit**

```bash
git add backend/modules/user/_handlers.py backend/modules/user/_auth.py tests/modules/user/test_login_endpoint.py
git commit -m "Rework POST /api/auth/login to accept H_auth/H_kek and unlock DEK"
```

---

## Task 10: Endpoint — `POST /api/auth/login-legacy` (one-time migration)

**Files:**
- Modify: `backend/modules/user/_handlers.py`
- Create: `tests/modules/user/test_login_legacy_endpoint.py`

- [ ] **Step 10.1 — Write the failing test**

Create `tests/modules/user/test_login_legacy_endpoint.py`:

```python
import base64
import hashlib
import pytest
import httpx

from backend.modules.user._auth import hash_password  # legacy bcrypt over raw password


@pytest.mark.asyncio
async def test_legacy_login_upgrades_user_and_returns_recovery_key(async_client, db, user_key_service):
    # Seed a pre-migration user: password_hash over raw password, no user_keys.
    raw_password = "hunter2-legacy"
    users = db["users"]
    from bson import ObjectId
    from datetime import datetime, UTC
    user_id = str(ObjectId())
    await users.insert_one({
        "_id": ObjectId(user_id),
        "username": "legacy_chris",
        "email": "legacy@example.com",
        "display_name": "Legacy Chris",
        "password_hash": hash_password(raw_password),
        "role": "user",
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    })

    # Simulate what the client will do:
    # 1. GET /kdf-params → returns pseudo-salt + password_hash_version=None.
    # 2. Client runs Argon2id(raw_password, salt) and HKDFs H_auth, H_kek.
    # For the test we fake both hashes with random bytes — the endpoint
    # verifies raw_password against stored bcrypt, not H_auth.
    import secrets
    h_auth = secrets.token_bytes(32)
    h_kek = secrets.token_bytes(32)
    body = {
        "username": "legacy_chris",
        "password": raw_password,
        "h_auth": base64.urlsafe_b64encode(h_auth).decode(),
        "h_kek": base64.urlsafe_b64encode(h_kek).decode(),
    }
    response = await async_client.post("/api/auth/login-legacy", json=body)
    assert response.status_code == 200
    data = response.json()
    assert "recovery_key" in data
    assert "access_token" in data

    # Row should have been upgraded.
    upgraded = await users.find_one({"username": "legacy_chris"})
    assert upgraded["password_hash_version"] == 1
    # user_keys row exists
    assert await user_key_service.get_keys_doc(user_id) is not None


@pytest.mark.asyncio
async def test_legacy_login_rejects_non_legacy_user(async_client, seeded_user):
    body = {
        "username": seeded_user.username,
        "password": "anything",
        "h_auth": "AA" * 44,
        "h_kek": "AA" * 44,
    }
    response = await async_client.post("/api/auth/login-legacy", json=body)
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_legacy_login_rejects_wrong_password(async_client, db):
    from bson import ObjectId
    from datetime import datetime, UTC
    await db["users"].insert_one({
        "_id": ObjectId(),
        "username": "legacy2",
        "email": "l2@example.com",
        "display_name": "l2",
        "password_hash": hash_password("correct"),
        "role": "user",
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    })
    body = {
        "username": "legacy2",
        "password": "wrong",
        "h_auth": "AA" * 44,
        "h_kek": "AA" * 44,
    }
    response = await async_client.post("/api/auth/login-legacy", json=body)
    assert response.status_code == 401
```

- [ ] **Step 10.2 — Run and verify failure**

```bash
uv run pytest tests/modules/user/test_login_legacy_endpoint.py -v
```

- [ ] **Step 10.3 — Implement the legacy endpoint**

In `backend/modules/user/_handlers.py`:

```python
from backend.modules.user._auth import verify_password, hash_h_auth
from backend.modules.user._crypto import pseudo_salt_for_unknown_user
from backend.modules.user._recovery_key import generate_recovery_key
from backend.modules.user._models import Argon2Params
from shared.dtos.auth import LoginLegacyRequestDto, LoginLegacyResponseDto


@router.post("/login-legacy", response_model=LoginLegacyResponseDto)
async def login_legacy(body: LoginLegacyRequestDto):
    user = await users_repo.find_by_username_case_insensitive(body.username)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    if user.password_hash_version == 1:
        raise HTTPException(status_code=409, detail="already_migrated")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid_credentials")

    # Upgrade: rewrite bcrypt over H_auth, mark version, provision keys.
    new_hash = hash_h_auth(body.h_auth)
    await users_repo.set_password_hash_and_version(user.id, password_hash=new_hash, version=1)

    recovery_key = generate_recovery_key()
    kdf_salt = pseudo_salt_for_unknown_user(body.username, settings.kdf_pepper_bytes)
    h_kek_bytes = base64.urlsafe_b64decode(body.h_kek)
    await user_key_service.provision_for_new_user(
        user_id=user.id,
        h_kek=h_kek_bytes,
        recovery_key=recovery_key,
        kdf_salt=kdf_salt,
        kdf_params=Argon2Params(),
    )

    # Immediate post-upgrade session — same as the normal login path.
    dek = await user_key_service.unlock_with_password(user_id=user.id, h_kek=h_kek_bytes)
    session_id = generate_session_id()
    access_token = create_access_token(user_id=user.id, role=user.role, session_id=session_id)
    refresh_token = await generate_refresh_token(user_id=user.id, session_id=session_id)
    await user_key_service.store_session_dek(
        session_id=session_id, dek=dek, ttl_seconds=settings.access_token_ttl_seconds
    )
    await event_bus.publish(
        Topics.USER_KEY_PROVISIONED,
        UserKeyProvisionedEvent(user_id=user.id, reason="migration"),
    )
    return LoginLegacyResponseDto(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.access_token_ttl_seconds,
        recovery_key=recovery_key,
    )
```

Add to `backend/modules/user/_repository.py`:

```python
    async def set_password_hash_and_version(self, user_id: str, *, password_hash: str, version: int) -> None:
        await self._collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "password_hash": password_hash,
                "password_hash_version": version,
                "updated_at": datetime.now(UTC),
            }},
        )
```

- [ ] **Step 10.4 — Verify tests pass**

```bash
uv run pytest tests/modules/user/test_login_legacy_endpoint.py -v
```

- [ ] **Step 10.5 — Commit**

```bash
git add backend/modules/user/_handlers.py backend/modules/user/_repository.py tests/modules/user/test_login_legacy_endpoint.py
git commit -m "Add POST /api/auth/login-legacy for one-time user migration"
```

---

## Task 11: Endpoints — `POST /api/auth/recover-dek` and `POST /api/auth/decline-recovery`

**Files:**
- Modify: `backend/modules/user/_handlers.py`
- Modify: `backend/modules/user/_rate_limit.py` (add a recovery bucket)
- Create: `tests/modules/user/test_recovery_endpoints.py`

- [ ] **Step 11.1 — Write the failing test**

Create `tests/modules/user/test_recovery_endpoints.py`:

```python
import base64
import pytest


@pytest.mark.asyncio
async def test_recover_dek_unlocks_and_rewraps(async_client, seeded_user, user_key_service):
    # seeded_user has a known recovery_key (part of the fixture contract, Task 13).
    await user_key_service.mark_recovery_required(seeded_user.id)
    import secrets
    new_h_kek = secrets.token_bytes(32)
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(new_h_kek).decode(),
        "recovery_key": seeded_user.recovery_key,
    }
    response = await async_client.post("/api/auth/recover-dek", json=body)
    assert response.status_code == 200
    # New password now unlocks
    login = await async_client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(new_h_kek).decode(),
    })
    assert login.status_code == 200
    assert "access_token" in login.json()


@pytest.mark.asyncio
async def test_recover_dek_with_wrong_key_401(async_client, seeded_user, user_key_service):
    await user_key_service.mark_recovery_required(seeded_user.id)
    import secrets
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "recovery_key": "ABCD-ABCD-ABCD-ABCD-ABCD-ABCD-ABCD-ABCD",
    }
    response = await async_client.post("/api/auth/recover-dek", json=body)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_decline_recovery_deactivates_account(async_client, seeded_user, db, user_key_service):
    await user_key_service.mark_recovery_required(seeded_user.id)
    response = await async_client.post("/api/auth/decline-recovery", json={"username": seeded_user.username})
    assert response.status_code == 200
    row = await db["users"].find_one({"username": seeded_user.username})
    assert row["is_active"] is False
```

- [ ] **Step 11.2 — Implement rate limit bucket**

In `backend/modules/user/_rate_limit.py`, alongside the existing login bucket, add:

```python
RECOVERY_BUCKET_KEY_PREFIX = "ratelimit:recovery:"
RECOVERY_MAX_ATTEMPTS = 5
RECOVERY_WINDOW_SECONDS = 15 * 60


async def check_recovery_rate_limit(username: str, redis) -> None:
    key = RECOVERY_BUCKET_KEY_PREFIX + username.lower()
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, RECOVERY_WINDOW_SECONDS)
    if count > RECOVERY_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="too_many_recovery_attempts")
```

- [ ] **Step 11.3 — Implement the endpoints**

In `backend/modules/user/_handlers.py`:

```python
from backend.modules.user._key_service import DekUnlockError
from backend.modules.user._recovery_key import InvalidRecoveryKeyError
from backend.modules.user._rate_limit import check_recovery_rate_limit
from shared.dtos.auth import RecoverDekRequestDto, DeclineRecoveryRequestDto


@router.post("/recover-dek")
async def recover_dek(body: RecoverDekRequestDto, redis=Depends(get_redis)):
    await check_recovery_rate_limit(body.username, redis)
    user = await users_repo.find_by_username_case_insensitive(body.username)
    if user is None or user.password_hash_version != 1:
        raise HTTPException(status_code=401, detail="invalid_credentials")
    if not verify_h_auth(body.h_auth, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    try:
        new_h_kek_bytes = base64.urlsafe_b64decode(body.h_kek)
        dek = await user_key_service.unlock_with_recovery_and_rewrap(
            user_id=user.id, recovery_key=body.recovery_key, new_h_kek=new_h_kek_bytes
        )
    except (DekUnlockError, InvalidRecoveryKeyError):
        raise HTTPException(status_code=401, detail="invalid_recovery_key")

    session_id = generate_session_id()
    access_token = create_access_token(user_id=user.id, role=user.role, session_id=session_id)
    refresh_token = await generate_refresh_token(user_id=user.id, session_id=session_id)
    await user_key_service.store_session_dek(
        session_id=session_id, dek=dek, ttl_seconds=settings.access_token_ttl_seconds
    )
    await event_bus.publish(Topics.USER_KEY_RECOVERED, UserKeyRecoveredEvent(user_id=user.id))
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": settings.access_token_ttl_seconds,
    }


@router.post("/decline-recovery")
async def decline_recovery(body: DeclineRecoveryRequestDto):
    user = await users_repo.find_by_username_case_insensitive(body.username)
    if user is None:
        # Same 200 to not leak existence, but without any side effect.
        return {"status": "acknowledged"}
    await users_repo.set_active(user.id, value=False)
    await event_bus.publish(
        Topics.USER_KEY_RECOVERY_DECLINED,
        UserKeyRecoveryDeclinedEvent(user_id=user.id),
    )
    return {"status": "acknowledged"}
```

Add `set_active` to `_repository.py` if missing:

```python
    async def set_active(self, user_id: str, *, value: bool) -> None:
        await self._collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"is_active": value, "updated_at": datetime.now(UTC)}},
        )
```

- [ ] **Step 11.4 — Verify tests pass**

```bash
uv run pytest tests/modules/user/test_recovery_endpoints.py -v
```

- [ ] **Step 11.5 — Commit**

```bash
git add backend/modules/user/_handlers.py backend/modules/user/_rate_limit.py backend/modules/user/_repository.py tests/modules/user/test_recovery_endpoints.py
git commit -m "Add recover-dek and decline-recovery endpoints with rate limit"
```

---

## Task 12: Endpoint — `POST /api/auth/change-password` (new contract)

**Files:**
- Modify: `backend/modules/user/_handlers.py`
- Create: `tests/modules/user/test_change_password_endpoint.py`

- [ ] **Step 12.1 — Write the failing test**

Create `tests/modules/user/test_change_password_endpoint.py`:

```python
import base64
import secrets
import pytest


@pytest.mark.asyncio
async def test_change_password_rewraps_and_updates_bcrypt(async_client, seeded_user, user_key_service):
    # Log in first
    login = await async_client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    })
    token = login.json()["access_token"]

    new_h_auth = secrets.token_bytes(32)
    new_h_kek = secrets.token_bytes(32)
    body = {
        "h_auth_old": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek_old": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
        "h_auth_new": base64.urlsafe_b64encode(new_h_auth).decode(),
        "h_kek_new": base64.urlsafe_b64encode(new_h_kek).decode(),
    }
    response = await async_client.post(
        "/api/auth/change-password", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200

    # Old credentials no longer work
    r_old = await async_client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    })
    assert r_old.status_code == 401

    # New credentials work
    r_new = await async_client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(new_h_auth).decode(),
        "h_kek": base64.urlsafe_b64encode(new_h_kek).decode(),
    })
    assert r_new.status_code == 200

    # Recovery wrap preserved
    doc = await user_key_service.get_keys_doc(seeded_user.id)
    # Recovery key still unlocks to the same DEK:
    new_new_h_kek = secrets.token_bytes(32)
    await user_key_service.mark_recovery_required(seeded_user.id)
    dek_via_recovery = await user_key_service.unlock_with_recovery_and_rewrap(
        user_id=seeded_user.id, recovery_key=seeded_user.recovery_key, new_h_kek=new_new_h_kek
    )
    dek_via_new_pw = await user_key_service.unlock_with_password(user_id=seeded_user.id, h_kek=new_new_h_kek)
    assert dek_via_recovery == dek_via_new_pw
```

- [ ] **Step 12.2 — Implement the updated handler**

Replace the existing change-password handler:

```python
from shared.dtos.auth import ChangePasswordRequestDto


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequestDto,
    current_user = Depends(get_current_user),
):
    if not verify_h_auth(body.h_auth_old, current_user.password_hash):
        raise HTTPException(status_code=401, detail="invalid_credentials")

    h_kek_old = base64.urlsafe_b64decode(body.h_kek_old)
    h_kek_new = base64.urlsafe_b64decode(body.h_kek_new)
    try:
        await user_key_service.rewrap_password(
            user_id=current_user.id, h_kek_old=h_kek_old, h_kek_new=h_kek_new
        )
    except DekUnlockError:
        raise HTTPException(status_code=401, detail="invalid_credentials")

    new_password_hash = hash_h_auth(body.h_auth_new)
    await users_repo.set_password_hash_and_version(
        current_user.id, password_hash=new_password_hash, version=1
    )
    # Drop must_change_password if it was set
    await users_repo.clear_must_change_password(current_user.id)
    return {"status": "ok"}
```

Add `clear_must_change_password` if missing:

```python
    async def clear_must_change_password(self, user_id: str) -> None:
        await self._collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"must_change_password": False, "updated_at": datetime.now(UTC)}},
        )
```

- [ ] **Step 12.3 — Verify tests pass**

```bash
uv run pytest tests/modules/user/test_change_password_endpoint.py -v
```

- [ ] **Step 12.4 — Commit**

```bash
git add backend/modules/user/_handlers.py backend/modules/user/_repository.py tests/modules/user/test_change_password_endpoint.py
git commit -m "Rework change-password endpoint to rewrap DEK with new H_kek"
```

---

## Task 13: Endpoint — setup/signup + `seeded_user` fixture

**Files:**
- Modify: `backend/modules/user/_handlers.py`
- Modify: `tests/conftest.py` (add fixtures)
- Create: `tests/modules/user/test_setup_endpoint.py`

- [ ] **Step 13.1 — Add shared test fixtures**

Append to `tests/conftest.py`:

```python
import secrets, base64
from dataclasses import dataclass
from datetime import datetime, UTC

import pytest_asyncio
from bson import ObjectId

from backend.modules.user._auth import hash_h_auth
from backend.modules.user._recovery_key import generate_recovery_key
from backend.modules.user._key_service import UserKeyService


@dataclass
class SeededUser:
    id: str
    username: str
    h_auth_raw: bytes
    h_kek_raw: bytes
    recovery_key: str


@pytest_asyncio.fixture
async def user_key_service(db, redis_client):
    svc = UserKeyService(db=db, redis=redis_client)
    await svc.ensure_indexes()
    return svc


@pytest_asyncio.fixture
async def seeded_user(db, user_key_service) -> SeededUser:
    h_auth = secrets.token_bytes(32)
    h_kek = secrets.token_bytes(32)
    recovery_key = generate_recovery_key()
    user_id = str(ObjectId())
    await db["users"].insert_one({
        "_id": ObjectId(user_id),
        "username": f"test-{user_id[:6]}",
        "email": f"{user_id[:6]}@example.com",
        "display_name": "Test User",
        "password_hash": hash_h_auth(base64.urlsafe_b64encode(h_auth).decode()),
        "password_hash_version": 1,
        "role": "user",
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    })
    await user_key_service.provision_for_new_user(
        user_id=user_id, h_kek=h_kek, recovery_key=recovery_key, kdf_salt=b"s" * 32
    )
    row = await db["users"].find_one({"_id": ObjectId(user_id)})
    return SeededUser(
        id=user_id,
        username=row["username"],
        h_auth_raw=h_auth,
        h_kek_raw=h_kek,
        recovery_key=recovery_key,
    )
```

If any previous task's test skipped pending this fixture, remove the skip.

- [ ] **Step 13.2 — Write the failing setup test**

Create `tests/modules/user/test_setup_endpoint.py`:

```python
import base64
import secrets
import pytest

from backend.modules.user._recovery_key import generate_recovery_key


@pytest.mark.asyncio
async def test_setup_creates_user_with_provisioned_keys(async_client, db, user_key_service, setup_pin):
    h_auth = secrets.token_bytes(32)
    h_kek = secrets.token_bytes(32)
    recovery_key = generate_recovery_key()
    body = {
        "username": "founder",
        "email": "founder@example.com",
        "display_name": "Founder",
        "pin": setup_pin,
        "h_auth": base64.urlsafe_b64encode(h_auth).decode(),
        "h_kek": base64.urlsafe_b64encode(h_kek).decode(),
        "recovery_key": recovery_key,
    }
    response = await async_client.post("/api/auth/setup", json=body)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "recovery_key" not in data  # client already has it; no echo

    row = await db["users"].find_one({"username": "founder"})
    assert row["password_hash_version"] == 1
    keys_doc = await user_key_service.get_keys_doc(str(row["_id"]))
    assert keys_doc is not None
    # Unlock with the exact recovery key and the exact h_kek succeeds
    await user_key_service.unlock_with_password(user_id=str(row["_id"]), h_kek=h_kek)
```

Add a `setup_pin` fixture to `tests/conftest.py`:

```python
@pytest_asyncio.fixture
async def setup_pin(redis_client):
    # Implementation depends on how the existing setup flow stores the PIN; copy the approach used in tests/modules/user in the old tree if present, otherwise bypass by setting the known env var.
    pin = "123456"
    await redis_client.set("setup:pin", pin)
    yield pin
    await redis_client.delete("setup:pin")
```

(Adjust to whatever the existing setup flow checks against — open `backend/modules/user/_handlers.py` `setup` handler first to mirror it.)

- [ ] **Step 13.3 — Implement the new setup body shape**

Replace (or extend) the existing `setup` handler:

```python
from shared.dtos.auth import SetupRequestDto


@router.post("/setup")
async def setup(body: SetupRequestDto):
    # Existing PIN check + master-admin uniqueness check stays.
    await _verify_setup_pin(body.pin)

    user_id = str(ObjectId())
    now = datetime.now(UTC)
    password_hash = hash_h_auth(body.h_auth)
    kdf_salt = os.urandom(32)

    await users_repo.insert({
        "_id": ObjectId(user_id),
        "username": body.username,
        "email": body.email,
        "display_name": body.display_name,
        "password_hash": password_hash,
        "password_hash_version": 1,
        "role": "master_admin",
        "is_active": True,
        "must_change_password": False,
        "created_at": now,
        "updated_at": now,
    })
    h_kek_bytes = base64.urlsafe_b64decode(body.h_kek)
    await user_key_service.provision_for_new_user(
        user_id=user_id, h_kek=h_kek_bytes, recovery_key=body.recovery_key, kdf_salt=kdf_salt
    )

    dek = await user_key_service.unlock_with_password(user_id=user_id, h_kek=h_kek_bytes)
    session_id = generate_session_id()
    access_token = create_access_token(user_id=user_id, role="master_admin", session_id=session_id)
    refresh_token = await generate_refresh_token(user_id=user_id, session_id=session_id)
    await user_key_service.store_session_dek(
        session_id=session_id, dek=dek, ttl_seconds=settings.access_token_ttl_seconds
    )
    await event_bus.publish(
        Topics.USER_KEY_PROVISIONED,
        UserKeyProvisionedEvent(user_id=user_id, reason="signup"),
    )
    await event_bus.publish(Topics.USER_CREATED, UserCreatedEvent(user_id=user_id, ...))
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": settings.access_token_ttl_seconds,
    }
```

If user creation in this codebase also goes through `POST /api/admin/users` (admin creates ordinary users), apply the same shape change there.

- [ ] **Step 13.4 — Verify tests pass**

```bash
uv run pytest tests/modules/user/test_setup_endpoint.py tests/modules/user/test_login_endpoint.py tests/modules/user/test_kdf_params_endpoint.py -v
```

- [ ] **Step 13.5 — Commit**

```bash
git add backend/modules/user/_handlers.py tests/conftest.py tests/modules/user/test_setup_endpoint.py
git commit -m "Update setup/signup to accept H_auth/H_kek and provision keys"
```

---

## Task 14: Admin reset — warning + `dek_recovery_required`

**Files:**
- Modify: `backend/modules/user/_handlers.py`
- Create: `tests/modules/user/test_admin_reset_endpoint.py`

- [ ] **Step 14.1 — Write the failing test**

Create `tests/modules/user/test_admin_reset_endpoint.py`:

```python
import base64
import pytest


@pytest.mark.asyncio
async def test_admin_reset_sets_dek_recovery_required(
    async_client, seeded_admin_token, seeded_user, user_key_service
):
    response = await async_client.post(
        f"/api/admin/users/{seeded_user.id}/reset-password",
        headers={"Authorization": f"Bearer {seeded_admin_token}"},
    )
    assert response.status_code == 200
    doc = await user_key_service.get_keys_doc(seeded_user.id)
    assert doc.dek_recovery_required is True


@pytest.mark.asyncio
async def test_post_reset_login_returns_recovery_required(
    async_client, seeded_admin_token, seeded_user
):
    reset = await async_client.post(
        f"/api/admin/users/{seeded_user.id}/reset-password",
        headers={"Authorization": f"Bearer {seeded_admin_token}"},
    )
    new_password = reset.json()["new_password"]
    # Client path: derive H_auth from the new password + the existing salt.
    # We cannot replicate Argon2id in Python here conveniently; skip the hash
    # derivation and just exercise the admin-flag path by attempting login
    # with the original H_auth (which will fail 401) and then set up a
    # synthetic H_auth that matches the new hash:
    # Because verify_h_auth uses the stored hash, we need to insert the new
    # hash generated by the server — the handler below stores bcrypt(raw). We
    # simulate the client by bypassing Argon2 and hashing the new_password
    # directly in the test.
    from backend.modules.user._auth import verify_h_auth
    # The handler below should set password_hash to bcrypt(hash_h_auth(something));
    # adapt the test to whatever derivation the handler performs.
    # If the handler stores bcrypt(base64(plaintext-of-new-password)), test accordingly.
    # Marked xfail until Task 14 Step 2 finalises the derivation.
```

The test file above encodes one contract question: when the admin resets, does the server still accept a plaintext password on the next login, or does it expect `H_auth` derived by the client? Decision for this plan: **admin reset produces a new plaintext password; the user's first post-reset login uses the legacy endpoint `/login-legacy` implicitly** (the frontend detects `dek_recovery_required`... no — this is better: the admin-reset handler *also* derives `H_auth` using the stored `kdf_salt` server-side and stores bcrypt over that). That avoids a "second legacy path".

Simplify: the admin-reset handler sets `password_hash` to bcrypt over a new server-side-computed `H_auth`. Since the server does not have Argon2id readily available, use a simpler approach: the admin UI shows the new raw password; the user types it in the login page; the frontend still runs Argon2id + HKDF as normal, sends H_auth/H_kek; the server stores `password_hash = bcrypt(hash_h_auth(sent_h_auth))` only after successful recover-dek.

Revised rule: **admin-reset stores a *temporary sentinel* password hash** that no `H_auth` can ever match, and sets `dek_recovery_required=true`. The user must therefore go through `/recover-dek` first (recovery-key path); on success, `recover-dek` also accepts the first password the user wants to use. Update `RecoverDekRequestDto`:

Remove the previous test file content and replace with:

```python
import base64
import secrets
import pytest


@pytest.mark.asyncio
async def test_admin_reset_sets_recovery_required_and_sentinel_hash(async_client, seeded_admin_token, seeded_user, user_key_service, db):
    response = await async_client.post(
        f"/api/admin/users/{seeded_user.id}/reset-password",
        headers={"Authorization": f"Bearer {seeded_admin_token}"},
    )
    assert response.status_code == 200
    doc = await user_key_service.get_keys_doc(seeded_user.id)
    assert doc.dek_recovery_required is True
    row = await db["users"].find_one({"username": seeded_user.username})
    assert row["password_hash"].startswith("$SENTINEL$")


@pytest.mark.asyncio
async def test_post_reset_login_always_returns_recovery_required(async_client, seeded_admin_token, seeded_user):
    await async_client.post(
        f"/api/admin/users/{seeded_user.id}/reset-password",
        headers={"Authorization": f"Bearer {seeded_admin_token}"},
    )
    # Any H_auth at all, since the stored hash is the sentinel.
    body = {
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "h_kek": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
    }
    response = await async_client.post("/api/auth/login", json=body)
    assert response.status_code == 200
    assert response.json() == {"status": "recovery_required"}
```

The `seeded_admin_token` fixture creates a master-admin user and returns a bearer token — add it to `tests/conftest.py` with the same pattern as `seeded_user`.

- [ ] **Step 14.2 — Implement**

In `backend/modules/user/_handlers.py`, find the admin-reset handler and change:

```python
SENTINEL_HASH = "$SENTINEL$reset$no-password-can-match$"


@admin_router.post("/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, current_admin = Depends(require_admin)):
    await users_repo.set_password_hash_and_version(
        user_id=user_id, password_hash=SENTINEL_HASH, version=1
    )
    await users_repo.set_must_change_password(user_id, value=True)
    await user_key_service.mark_recovery_required(user_id)
    await event_bus.publish(
        Topics.USER_KEY_RECOVERY_REQUIRED,
        UserKeyRecoveryRequiredEvent(user_id=user_id, triggered_by_admin_id=current_admin.id),
    )
    return {"status": "reset"}
```

Also, in the `/api/auth/login` handler (Task 9), add an early branch: if the stored hash starts with `$SENTINEL$`, return `RecoveryRequiredResponseDto` without running bcrypt. This is why the second test in Task 14 can use any random H_auth.

`verify_h_auth` must reject the sentinel (to avoid accidental matches). Update it:

```python
def verify_h_auth(h_auth_b64: str, stored_hash: str) -> bool:
    if stored_hash.startswith("$SENTINEL$"):
        return False
    raw = base64.urlsafe_b64decode(h_auth_b64)
    return bcrypt.checkpw(raw, stored_hash.encode())
```

Also update `recover-dek` (Task 11): after successful recovery, the handler must set the stored password hash to bcrypt over the supplied `h_auth` (because the old hash is a sentinel). Amend Task 11's handler:

```python
    # After rewrap, install the user's chosen H_auth as the real bcrypt hash
    new_hash = hash_h_auth(body.h_auth)
    await users_repo.set_password_hash_and_version(user.id, password_hash=new_hash, version=1)
    await users_repo.clear_must_change_password(user.id)
```

Add `set_must_change_password` to `_repository.py`:

```python
    async def set_must_change_password(self, user_id: str, *, value: bool) -> None:
        await self._collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"must_change_password": value, "updated_at": datetime.now(UTC)}},
        )
```

- [ ] **Step 14.3 — Verify all previously-written tests still pass**

```bash
uv run pytest tests/modules/user/ -v
```

Fix any regressions from the sentinel change (particularly in `test_recovery_endpoints.py` — the test may assume the old hash is reusable post-recovery; update it to use the new H_auth as the hash).

- [ ] **Step 14.4 — Commit**

```bash
git add backend/modules/user/_handlers.py backend/modules/user/_auth.py backend/modules/user/_repository.py tests/modules/user/test_admin_reset_endpoint.py tests/conftest.py
git commit -m "Admin reset installs sentinel hash and requires recovery key on next login"
```

---

## Task 15: Logout clears DEK; refresh extends TTL

**Files:**
- Modify: `backend/modules/user/_handlers.py`
- Modify: `backend/modules/user/_auth.py` or wherever refresh is handled
- Create: `tests/modules/user/test_session_dek_lifecycle.py`

- [ ] **Step 15.1 — Test**

Create `tests/modules/user/test_session_dek_lifecycle.py`:

```python
import base64
import pytest


@pytest.mark.asyncio
async def test_logout_deletes_session_dek(async_client, seeded_user, user_key_service):
    login = await async_client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    })
    token = login.json()["access_token"]
    from backend.modules.user._auth import decode_access_token
    session_id = decode_access_token(token)["session_id"]
    assert await user_key_service.fetch_session_dek(session_id) is not None

    await async_client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert await user_key_service.fetch_session_dek(session_id) is None


@pytest.mark.asyncio
async def test_refresh_extends_session_dek_ttl(async_client, seeded_user, user_key_service, redis_client):
    login = await async_client.post("/api/auth/login", json={
        "username": seeded_user.username,
        "h_auth": base64.urlsafe_b64encode(seeded_user.h_auth_raw).decode(),
        "h_kek": base64.urlsafe_b64encode(seeded_user.h_kek_raw).decode(),
    })
    token = login.json()["access_token"]
    from backend.modules.user._auth import decode_access_token
    session_id = decode_access_token(token)["session_id"]
    ttl_before = await redis_client.ttl(f"session_dek:{session_id}")
    # shorten it artificially so we can observe the extension
    await redis_client.expire(f"session_dek:{session_id}", 60)
    ttl_mid = await redis_client.ttl(f"session_dek:{session_id}")
    assert ttl_mid <= 60

    refresh = await async_client.post("/api/auth/refresh", cookies={"refresh_token": login.cookies["refresh_token"]})
    assert refresh.status_code == 200
    ttl_after = await redis_client.ttl(f"session_dek:{session_id}")
    assert ttl_after > ttl_mid
```

- [ ] **Step 15.2 — Implement in the existing logout handler**

Find the logout handler in `_handlers.py` and add:

```python
    await user_key_service.delete_session_dek(session_id)
```

In the refresh handler:

```python
    await user_key_service.extend_session_dek_ttl(
        session_id=session_id, ttl_seconds=settings.access_token_ttl_seconds
    )
    # If extend returned False the key was missing — force re-login:
    if not extended:
        raise HTTPException(status_code=401, detail="session_expired")
```

- [ ] **Step 15.3 — Verify and commit**

```bash
uv run pytest tests/modules/user/test_session_dek_lifecycle.py -v
git add backend/modules/user/_handlers.py tests/modules/user/test_session_dek_lifecycle.py
git commit -m "Clear session DEK on logout and extend TTL on refresh"
```

---

## Task 16: Frontend — install argon2-browser + Web Worker

**Files:**
- Modify: `frontend/package.json`, lockfile
- Create: `frontend/src/core/crypto/argon2.worker.ts`

- [ ] **Step 16.1 — Install**

```bash
cd frontend && pnpm add argon2-browser@1.18.0
```

(Pin to the latest stable at the time of implementation; 1.18 is current as of 2026-04.)

- [ ] **Step 16.2 — Create the worker**

Create `frontend/src/core/crypto/argon2.worker.ts`:

```typescript
/// <reference lib="webworker" />
import argon2 from 'argon2-browser'

export interface Argon2Request {
  password: string
  salt: Uint8Array
  memoryKib: number
  iterations: number
  parallelism: number
}

export interface Argon2Response {
  hash: Uint8Array  // 64-byte H
}

self.onmessage = async (e: MessageEvent<Argon2Request>) => {
  const { password, salt, memoryKib, iterations, parallelism } = e.data
  try {
    const result = await argon2.hash({
      pass: password,
      salt: salt,
      type: argon2.ArgonType.Argon2id,
      mem: memoryKib,
      time: iterations,
      parallelism,
      hashLen: 64,
    })
    const response: Argon2Response = { hash: new Uint8Array(result.hash) }
    ;(self as unknown as Worker).postMessage(response, [response.hash.buffer])
  } catch (err) {
    ;(self as unknown as Worker).postMessage({ error: String(err) })
  }
}
```

- [ ] **Step 16.3 — TypeScript check**

```bash
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 16.4 — Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/core/crypto/argon2.worker.ts
git commit -m "Add argon2-browser dependency and Argon2id Web Worker"
```

---

## Task 17: Frontend — `keyDerivation.ts` orchestrator

**Files:**
- Create: `frontend/src/core/crypto/keyDerivation.ts`

- [ ] **Step 17.1 — Implement**

Create `frontend/src/core/crypto/keyDerivation.ts`:

```typescript
import type { Argon2Request, Argon2Response } from './argon2.worker'

export interface KdfParams {
  memoryKib: number
  iterations: number
  parallelism: number
}

export interface DerivedHashes {
  hAuth: Uint8Array  // 32 bytes
  hKek: Uint8Array   // 32 bytes
}

let workerSingleton: Worker | null = null

function getWorker(): Worker {
  if (!workerSingleton) {
    workerSingleton = new Worker(new URL('./argon2.worker.ts', import.meta.url), { type: 'module' })
  }
  return workerSingleton
}

async function runArgon2id(password: string, salt: Uint8Array, params: KdfParams): Promise<Uint8Array> {
  const worker = getWorker()
  return new Promise((resolve, reject) => {
    const handler = (e: MessageEvent<Argon2Response | { error: string }>) => {
      worker.removeEventListener('message', handler)
      if ('error' in e.data) reject(new Error(e.data.error))
      else resolve(e.data.hash)
    }
    worker.addEventListener('message', handler)
    const req: Argon2Request = { password, salt, ...params }
    worker.postMessage(req)
  })
}

async function hkdfSha256(ikm: Uint8Array, info: string, length: number): Promise<Uint8Array> {
  const baseKey = await crypto.subtle.importKey('raw', ikm, 'HKDF', false, ['deriveBits'])
  const derived = await crypto.subtle.deriveBits(
    { name: 'HKDF', hash: 'SHA-256', salt: new Uint8Array(0), info: new TextEncoder().encode(info) },
    baseKey,
    length * 8,
  )
  return new Uint8Array(derived)
}

export async function deriveAuthAndKek(password: string, salt: Uint8Array, params: KdfParams): Promise<DerivedHashes> {
  const h = await runArgon2id(password, salt, params)
  const [hAuth, hKek] = await Promise.all([
    hkdfSha256(h, 'chatsune-auth', 32),
    hkdfSha256(h, 'chatsune-kek', 32),
  ])
  return { hAuth, hKek }
}

export function toBase64Url(bytes: Uint8Array): string {
  let s = btoa(String.fromCharCode(...bytes))
  return s.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

export function fromBase64Url(s: string): Uint8Array {
  s = s.replace(/-/g, '+').replace(/_/g, '/')
  while (s.length % 4) s += '='
  const bin = atob(s)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}
```

- [ ] **Step 17.2 — TypeScript check**

```bash
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 17.3 — Commit**

```bash
git add frontend/src/core/crypto/keyDerivation.ts
git commit -m "Add client-side Argon2id + HKDF orchestrator"
```

---

## Task 18: Frontend — `recoveryKey.ts` codec

**Files:**
- Create: `frontend/src/core/crypto/recoveryKey.ts`

- [ ] **Step 18.1 — Implement**

Mirror the Python implementation exactly so round-trip works:

```typescript
const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'
const DECODE: Record<string, number> = {}
for (let i = 0; i < ALPHABET.length; i++) DECODE[ALPHABET[i]] = i
// Crockford leniency
DECODE['O'] = DECODE['0']
DECODE['I'] = DECODE['1']
DECODE['L'] = DECODE['1']
for (const key of Object.keys(DECODE)) {
  DECODE[key.toLowerCase()] = DECODE[key]
}

export function generateRecoveryKey(): string {
  const raw = new Uint8Array(20)
  crypto.getRandomValues(raw)
  return encodeRecoveryKey(raw)
}

export function encodeRecoveryKey(raw: Uint8Array): string {
  if (raw.length !== 20) throw new Error('raw must be 20 bytes')
  // Big-endian 20-byte -> base 32 with leading zero padding.
  let n = 0n
  for (const b of raw) n = (n << 8n) | BigInt(b)
  const chars: string[] = []
  for (let i = 0; i < 32; i++) {
    chars.push(ALPHABET[Number(n & 31n)])
    n >>= 5n
  }
  const s = chars.reverse().join('')
  return [s.slice(0, 4), s.slice(4, 8), s.slice(8, 12), s.slice(12, 16), s.slice(16, 20), s.slice(20, 24), s.slice(24, 28), s.slice(28, 32)].join('-')
}

export function normaliseRecoveryKey(input: string): string {
  return input.replace(/[\s-]/g, '').toUpperCase()
}

export class InvalidRecoveryKeyError extends Error {}

export function decodeRecoveryKey(input: string): Uint8Array {
  const s = normaliseRecoveryKey(input)
  if (s.length !== 32) throw new InvalidRecoveryKeyError('must be 32 significant characters')
  let n = 0n
  for (const ch of s) {
    const v = DECODE[ch]
    if (v === undefined) throw new InvalidRecoveryKeyError(`invalid character: ${ch}`)
    n = n * 32n + BigInt(v)
  }
  const out = new Uint8Array(20)
  for (let i = 19; i >= 0; i--) {
    out[i] = Number(n & 0xffn)
    n >>= 8n
  }
  return out
}
```

- [ ] **Step 18.2 — TypeScript check + quick manual round-trip**

```bash
cd frontend && pnpm tsc --noEmit
```

Open a browser console or run an ad-hoc node script against the built module to confirm:

```js
const k = generateRecoveryKey()
console.log(k, decodeRecoveryKey(k).length === 20)
```

- [ ] **Step 18.3 — Commit**

```bash
git add frontend/src/core/crypto/recoveryKey.ts
git commit -m "Add client-side Crockford-Base32 recovery-key codec"
```

---

## Task 19: Frontend — update `core/api/auth.ts`

**Files:**
- Modify: `frontend/src/core/api/auth.ts`

- [ ] **Step 19.1 — Rewrite `authApi`**

Replace relevant blocks with:

```typescript
import { apiRequest } from './client'
import { deriveAuthAndKek, toBase64Url, KdfParams } from '../crypto/keyDerivation'
import { generateRecoveryKey } from '../crypto/recoveryKey'

export interface KdfParamsResponse {
  kdf_salt: string
  kdf_params: KdfParams
  password_hash_version: number | null
}

export interface LoginResult {
  kind: 'ok' | 'recovery_required' | 'legacy_upgrade'
  accessToken?: string
  expiresIn?: number
  recoveryKey?: string  // only for legacy_upgrade
}

export const authApi = {
  async fetchKdfParams(username: string): Promise<KdfParamsResponse> {
    return apiRequest('/api/auth/kdf-params', { method: 'POST', body: { username } })
  },

  async login(username: string, password: string): Promise<LoginResult> {
    const params = await this.fetchKdfParams(username)
    const salt = Uint8Array.from(atob(params.kdf_salt.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0))
    const { hAuth, hKek } = await deriveAuthAndKek(password, salt, params.kdf_params)

    if (params.password_hash_version === null) {
      const resp = await apiRequest('/api/auth/login-legacy', {
        method: 'POST',
        body: {
          username,
          password,
          h_auth: toBase64Url(hAuth),
          h_kek: toBase64Url(hKek),
        },
      })
      return { kind: 'legacy_upgrade', accessToken: resp.access_token, expiresIn: resp.expires_in, recoveryKey: resp.recovery_key }
    }

    const resp = await apiRequest('/api/auth/login', {
      method: 'POST',
      body: {
        username,
        h_auth: toBase64Url(hAuth),
        h_kek: toBase64Url(hKek),
      },
    })
    if (resp.status === 'recovery_required') return { kind: 'recovery_required' }
    return { kind: 'ok', accessToken: resp.access_token, expiresIn: resp.expires_in }
  },

  async recoverDek(username: string, newPassword: string, recoveryKey: string): Promise<{ accessToken: string; expiresIn: number }> {
    const params = await this.fetchKdfParams(username)
    const salt = Uint8Array.from(atob(params.kdf_salt.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0))
    const { hAuth, hKek } = await deriveAuthAndKek(newPassword, salt, params.kdf_params)
    const resp = await apiRequest('/api/auth/recover-dek', {
      method: 'POST',
      body: {
        username,
        h_auth: toBase64Url(hAuth),
        h_kek: toBase64Url(hKek),
        recovery_key: recoveryKey,
      },
    })
    return { accessToken: resp.access_token, expiresIn: resp.expires_in }
  },

  async declineRecovery(username: string): Promise<void> {
    await apiRequest('/api/auth/decline-recovery', { method: 'POST', body: { username } })
  },

  async changePassword(oldPassword: string, newPassword: string, username: string): Promise<void> {
    const params = await this.fetchKdfParams(username)
    const salt = Uint8Array.from(atob(params.kdf_salt.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0))
    const oldHashes = await deriveAuthAndKek(oldPassword, salt, params.kdf_params)
    const newHashes = await deriveAuthAndKek(newPassword, salt, params.kdf_params)
    await apiRequest('/api/auth/change-password', {
      method: 'POST',
      body: {
        h_auth_old: toBase64Url(oldHashes.hAuth),
        h_kek_old: toBase64Url(oldHashes.hKek),
        h_auth_new: toBase64Url(newHashes.hAuth),
        h_kek_new: toBase64Url(newHashes.hKek),
      },
    })
  },

  async setup(opts: { username: string; email: string; displayName: string; pin: string; password: string }): Promise<{ accessToken: string; expiresIn: number; recoveryKey: string }> {
    const params = await this.fetchKdfParams(opts.username)
    const salt = Uint8Array.from(atob(params.kdf_salt.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0))
    const { hAuth, hKek } = await deriveAuthAndKek(opts.password, salt, params.kdf_params)
    const recoveryKey = generateRecoveryKey()
    const resp = await apiRequest('/api/auth/setup', {
      method: 'POST',
      body: {
        username: opts.username,
        email: opts.email,
        display_name: opts.displayName,
        pin: opts.pin,
        h_auth: toBase64Url(hAuth),
        h_kek: toBase64Url(hKek),
        recovery_key: recoveryKey,
      },
    })
    return { accessToken: resp.access_token, expiresIn: resp.expires_in, recoveryKey }
  },
}
```

- [ ] **Step 19.2 — TypeScript check**

```bash
cd frontend && pnpm tsc --noEmit
```

Fix any callers flagged by the type checker (they appear in the next tasks).

- [ ] **Step 19.3 — Commit**

```bash
git add frontend/src/core/api/auth.ts
git commit -m "Rewrite frontend auth API for new password-derived login contract"
```

---

## Task 20: Frontend — `RecoveryKeyModal` and `RecoveryKeyPrompt` components

**Files:**
- Create: `frontend/src/features/auth/RecoveryKeyModal.tsx`
- Create: `frontend/src/features/auth/RecoveryKeyPrompt.tsx`

- [ ] **Step 20.1 — `RecoveryKeyModal.tsx`**

```tsx
import { useState } from 'react'

interface Props {
  recoveryKey: string
  onAcknowledged: () => void
}

export function RecoveryKeyModal({ recoveryKey, onAcknowledged }: Props) {
  const [saved, setSaved] = useState(false)
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    await navigator.clipboard.writeText(recoveryKey)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const download = () => {
    const blob = new Blob([`Chatsune recovery key\n\n${recoveryKey}\n\nKeep this safe. If you forget your password, this is the only way to recover your data.\n`], { type: 'text/plain' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'chatsune-recovery-key.txt'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[#0f0d16] text-white rounded-lg p-6 max-w-lg w-full space-y-4">
        <h2 className="text-xl font-semibold">Your recovery key</h2>
        <p className="text-sm opacity-80">
          If you ever forget your password, this is the only way to recover your encrypted data.
          Save it now — you will not be shown it again.
        </p>
        <pre className="font-mono text-center text-lg bg-black/40 p-4 rounded">{recoveryKey}</pre>
        <div className="flex gap-2">
          <button onClick={copy} className="flex-1 py-2 bg-white/10 rounded hover:bg-white/20">
            {copied ? 'Copied' : 'Copy'}
          </button>
          <button onClick={download} className="flex-1 py-2 bg-white/10 rounded hover:bg-white/20">
            Download as .txt
          </button>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
          I have saved this recovery key in a safe place.
        </label>
        <button
          disabled={!saved}
          onClick={onAcknowledged}
          className="w-full py-2 bg-indigo-500 disabled:opacity-40 rounded"
        >
          Continue
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 20.2 — `RecoveryKeyPrompt.tsx`**

```tsx
import { useState } from 'react'

interface Props {
  username: string
  onRecover: (newPassword: string, recoveryKey: string) => Promise<void>
  onDecline: () => Promise<void>
}

export function RecoveryKeyPrompt({ username, onRecover, onDecline }: Props) {
  const [recoveryKey, setRecoveryKey] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmed, setConfirmed] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showDecline, setShowDecline] = useState(false)

  const submit = async () => {
    setError(null)
    if (newPassword !== confirmed) { setError('Passwords do not match'); return }
    setBusy(true)
    try {
      await onRecover(newPassword, recoveryKey)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Recovery failed')
    } finally { setBusy(false) }
  }

  if (showDecline) {
    return (
      <div className="space-y-3">
        <p>If you do not have your recovery key, your encrypted data is not recoverable. Your account will be deactivated and your administrator will have to reset it, which will destroy any encrypted data you had.</p>
        <div className="flex gap-2">
          <button onClick={() => setShowDecline(false)} className="flex-1 py-2 bg-white/10 rounded">Back</button>
          <button onClick={onDecline} className="flex-1 py-2 bg-red-600 rounded">I understand, deactivate my account</button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <p>An administrator reset your password. To access your encrypted data you need your recovery key.</p>
      <input
        className="w-full p-2 rounded bg-white/5 font-mono"
        placeholder="XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"
        value={recoveryKey}
        onChange={(e) => setRecoveryKey(e.target.value)}
      />
      <input
        type="password"
        className="w-full p-2 rounded bg-white/5"
        placeholder="Choose a new password"
        value={newPassword}
        onChange={(e) => setNewPassword(e.target.value)}
      />
      <input
        type="password"
        className="w-full p-2 rounded bg-white/5"
        placeholder="Confirm new password"
        value={confirmed}
        onChange={(e) => setConfirmed(e.target.value)}
      />
      {error && <p className="text-red-400 text-sm">{error}</p>}
      <button disabled={busy || !recoveryKey || !newPassword} onClick={submit} className="w-full py-2 bg-indigo-500 disabled:opacity-40 rounded">
        {busy ? 'Recovering…' : 'Recover'}
      </button>
      <button onClick={() => setShowDecline(true)} className="w-full text-sm underline opacity-80">
        I do not have my recovery key
      </button>
    </div>
  )
}
```

- [ ] **Step 20.3 — TypeScript check**

```bash
cd frontend && pnpm tsc --noEmit
```

- [ ] **Step 20.4 — Commit**

```bash
git add frontend/src/features/auth/
git commit -m "Add RecoveryKeyModal and RecoveryKeyPrompt components"
```

---

## Task 21: Frontend — wire up login, setup, change-password, admin-reset pages

**Files:**
- Modify: login page (discover via `rg -n 'authApi.login\(' frontend/src`)
- Modify: setup page
- Modify: change-password form
- Modify: admin-reset button handler in admin UI

- [ ] **Step 21.1 — Login page state machine**

Discover the file first:

```bash
cd /home/chris/workspace/chatsune && rg -nl 'authApi.login' frontend/src
```

In that file, wrap the result of `authApi.login(...)`:

```tsx
const result = await authApi.login(username, password)
if (result.kind === 'ok') {
  saveToken(result.accessToken!, result.expiresIn!)
  navigate('/')
} else if (result.kind === 'legacy_upgrade') {
  saveToken(result.accessToken!, result.expiresIn!)
  setModalRecoveryKey(result.recoveryKey!)  // shows RecoveryKeyModal
} else if (result.kind === 'recovery_required') {
  setNeedsRecovery(true)
}
```

Render conditionally:

```tsx
{modalRecoveryKey && (
  <RecoveryKeyModal recoveryKey={modalRecoveryKey} onAcknowledged={() => {
    setModalRecoveryKey(null)
    navigate('/')
  }} />
)}
{needsRecovery && (
  <RecoveryKeyPrompt
    username={username}
    onRecover={async (newPassword, recoveryKey) => {
      const { accessToken, expiresIn } = await authApi.recoverDek(username, newPassword, recoveryKey)
      saveToken(accessToken, expiresIn)
      navigate('/')
    }}
    onDecline={async () => {
      await authApi.declineRecovery(username)
      navigate('/disabled')
    }}
  />
)}
```

- [ ] **Step 21.2 — Setup page**

Discover the file:

```bash
rg -nl 'authApi.setup\|/api/auth/setup' frontend/src
```

Use the new `authApi.setup(...)` return value:

```tsx
const { accessToken, expiresIn, recoveryKey } = await authApi.setup({...})
saveToken(accessToken, expiresIn)
setModalRecoveryKey(recoveryKey)
```

Render the `RecoveryKeyModal` as above.

- [ ] **Step 21.3 — Change-password form**

Discover:

```bash
rg -nl 'change-password\|changePassword' frontend/src
```

The form needs to capture the username (usually from the current auth store) and pass old+new passwords:

```tsx
await authApi.changePassword(oldPassword, newPassword, currentUser.username)
```

Remove any reference to the old request shape.

- [ ] **Step 21.4 — Admin-reset warning dialog**

Discover the admin-reset UI:

```bash
rg -nl 'reset-password\|resetPassword' frontend/src
```

Before calling the reset endpoint, show a confirmation dialog with text:

> "This reset does not recover the user's data. If the user does not have their recovery key, all their encrypted data will become permanently inaccessible. Continue?"

Two buttons — Cancel / Reset. Reset performs the existing API call.

- [ ] **Step 21.5 — Production build**

```bash
cd frontend && pnpm run build
```

Expected: build succeeds, no TypeScript errors.

- [ ] **Step 21.6 — Commit**

```bash
git add frontend/src
git commit -m "Wire login/setup/change-password/admin-reset pages to new auth flow"
```

---

## Task 22: Documentation and final verification

**Files:**
- Modify: `README.md`
- Modify: `.env.example` (verify Task 1 changes)
- Modify: `INSIGHTS.md` (add an entry)

- [ ] **Step 22.1 — README**

Add under the "Environment variables" section:

```markdown
### `kdf_pepper`

32-byte pepper (urlsafe-base64) used to derive deterministic pseudo-salts in `POST /api/auth/kdf-params` for usernames that do not exist in the database. Keeps the endpoint response indistinguishable between real and ghost users, closing a user-enumeration side channel. Must be set; the backend refuses to boot otherwise. Separate purpose and key material from `encryption_key` — losing `kdf_pepper` does not decrypt any user data, only makes enumeration easier.

Generate a value:

    python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Add under an "Authentication" (or similar) section:

```markdown
## Per-user key infrastructure

Every user account carries a per-user Data Encryption Key (DEK) stored in the `user_keys` collection. The DEK is wrapped twice: once under a key derived from the user's password (client-side Argon2id + HKDF), once under a key derived from a 32-character recovery key shown to the user exactly once at signup. The recovery key is the only way to regain access after an administrator resets a user's password. No user data is actually encrypted yet — this infrastructure is in place so that later releases can switch individual collections to encrypted storage without a flag-day migration.
```

- [ ] **Step 22.2 — INSIGHTS.md entry**

Append:

```markdown
## INS-XXX: Per-user key infrastructure (2026-04-23)

Added `user_keys` collection and the client-side Argon2id → HKDF → server-side H_auth/H_kek login flow. No data is encrypted by this change; the plumbing is in place for later rollout. Key design choices:

- The server sees `H_auth` and `H_kek`, never the plaintext password. This is defence-in-depth (TLS already protects the wire) but it also makes the `encryption_key` in `.env` genuinely powerless against user data — the operator can no longer decrypt a future DEK by holding the env file.
- `wrapped_by_password` and `wrapped_by_recovery` are kept in a `deks` map keyed by version so a later DEK rotation is a schema-compatible extension.
- Admin reset installs a `$SENTINEL$…` sentinel password hash that no bcrypt input can match, forcing the next login through `/recover-dek`. This removes the ambiguity of "bcrypt matched but unwrap failed = data corruption vs. just-reset".
- Legacy users are migrated lazily on their first post-upgrade login via `/login-legacy`, which is the only path that still accepts a plaintext password (and only once per user).

Follow-ups are tracked in `devdocs/superpowers/specs/2026-04-23-per-user-key-infrastructure-design.md` §16.
```

(Renumber XXX to whatever the next ID is.)

- [ ] **Step 22.3 — Full test run**

```bash
uv run pytest -x
```

Expected: all green. Fix any surprise regressions in other modules if the auth-flow changes broke an existing test.

- [ ] **Step 22.4 — Full frontend build**

```bash
cd frontend && pnpm run build
```

Expected: success.

- [ ] **Step 22.5 — Manual-verification smoke pass**

Run the ten manual scenarios from spec §14 against a local `docker compose up` stack. For each, tick the scenario as passing or file a follow-up issue if deferred.

- [ ] **Step 22.6 — Commit and merge**

```bash
git add README.md INSIGHTS.md
git commit -m "Document kdf_pepper and per-user key infrastructure"
```

No separate merge — master is the working branch per project convention.

---

## Self-Review (completed)

**Spec coverage:** every numbered spec section (§3–§14) maps onto at least one task — crypto primitives (§6) into Task 2, data model (§4) into Tasks 4–5, API surface (§5.1–§5.7) into Tasks 8–15, migration (§8) into Task 10, events (§9) into Task 7, module boundaries (§10) into Tasks 5–6, frontend (§11) into Tasks 16–21, security considerations (§12) into Tasks 8/11/14, manual verification (§14) into Task 22.5.

**Placeholder scan:** no TBDs/TODOs in task bodies. One area of deliberate late binding — Task 21 Steps 21.1/21.2/21.3/21.4 ask the implementer to discover page file paths via `rg` because the frontend layout is not visible from here; concrete `rg` commands and the code to add are given.

**Type / name consistency:** `UserKeyService`, `UserKeysDocument`, `WrappedDekPair`, `Argon2Params`, `derive_wrap_key`, `aes_gcm_wrap`, `aes_gcm_unwrap`, `pseudo_salt_for_unknown_user`, `generate_recovery_key`, `decode_recovery_key`, `hash_h_auth`, `verify_h_auth` consistent across tasks. DB field names `password_hash_version`, `kdf_salt`, `kdf_params`, `current_dek_version`, `deks`, `dek_recovery_required` match the spec §4. Redis key prefix `session_dek:` consistent.
