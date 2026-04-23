"""UserKeyService — DEK lifecycle and Redis session-DEK store.

Responsibilities:
- Provision a new user's key material (generate DEK, wrap it twice).
- Unlock a DEK using the password-derived KEK (h_kek).
- Unlock a DEK using the recovery key and rewrap the password side.
- Rewrap the password side after a password change.
- Store / fetch / extend / delete session DEKs in Redis.
- Maintain the dek_recovery_required flag in MongoDB.

All byte parameters and return values are raw ``bytes`` — no base64
encoding at this layer.
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
from backend.modules.user._models import Argon2Params, UserKeysDocument, WrappedDekPair
from backend.modules.user._recovery_key import decode_recovery_key

_SESSION_DEK_PREFIX = "session_dek:"


class DekUnlockError(Exception):
    """Raised when a DEK cannot be decrypted with the supplied key material."""


class UserKeyNotFoundError(Exception):
    """Raised when no key document exists for the requested user."""


class UserKeyService:
    """Manages per-user DEK lifecycle and Redis-backed session-DEK storage."""

    def __init__(self, *, db: AsyncIOMotorDatabase, redis: Redis) -> None:
        self._repo = UserKeysRepository(db)
        self._redis = redis

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    async def ensure_indexes(self) -> None:
        """Delegate index creation to the repository (idempotent)."""
        await self._repo.ensure_indexes()

    # ------------------------------------------------------------------
    # Provisioning
    # ------------------------------------------------------------------

    async def provision_for_new_user(
        self,
        *,
        user_id: str,
        h_kek: bytes,
        recovery_key: str,
        kdf_salt: bytes,
        kdf_params: Argon2Params | None = None,
    ) -> None:
        """Generate a DEK, wrap it under both the password KEK and the recovery
        key, and persist the resulting document.

        The plaintext DEK is overwritten in memory immediately after wrapping.
        """
        if kdf_params is None:
            kdf_params = Argon2Params()

        # Generate the plaintext DEK.
        dek = os.urandom(32)

        # Derive wrap keys.
        key_pw = derive_wrap_key(h_kek, info=b"dek-wrap")
        key_rec = derive_wrap_key(decode_recovery_key(recovery_key), info=b"dek-wrap")

        # Wrap.
        wrapped_by_password = aes_gcm_wrap(key_pw, dek)
        wrapped_by_recovery = aes_gcm_wrap(key_rec, dek)

        # Erase plaintext DEK and sensitive key material from memory.
        dek = b""
        key_pw = b""
        key_rec = b""

        now = datetime.now(UTC)
        doc = UserKeysDocument(
            user_id=user_id,
            kdf_salt=kdf_salt,
            kdf_params=kdf_params,
            current_dek_version=1,
            deks={
                "1": WrappedDekPair(
                    wrapped_by_password=wrapped_by_password,
                    wrapped_by_recovery=wrapped_by_recovery,
                    created_at=now,
                )
            },
            dek_recovery_required=False,
            created_at=now,
            updated_at=now,
        )
        await self._repo.insert(doc)

    # ------------------------------------------------------------------
    # Document access
    # ------------------------------------------------------------------

    async def get_keys_doc(self, user_id: str) -> UserKeysDocument | None:
        """Return the raw key document for a user, or None if not found."""
        return await self._repo.get_by_user_id(user_id)

    # ------------------------------------------------------------------
    # Unlock helpers
    # ------------------------------------------------------------------

    async def unlock_with_password(self, *, user_id: str, h_kek: bytes) -> bytes:
        """Decrypt and return the current DEK using the password-derived KEK.

        Raises :class:`DekUnlockError` on authentication failure.
        Raises :class:`UserKeyNotFoundError` if the user has no key document.
        """
        doc = await self._require_keys_doc(user_id)
        version = str(doc.current_dek_version)
        wrapped = doc.deks[version].wrapped_by_password
        key_pw = derive_wrap_key(h_kek, info=b"dek-wrap")
        try:
            return aes_gcm_unwrap(key_pw, wrapped)
        except AesGcmUnwrapError as exc:
            raise DekUnlockError("Password KEK did not authenticate the wrapped DEK") from exc

    async def unlock_with_recovery_and_rewrap(
        self,
        *,
        user_id: str,
        recovery_key: str,
        new_h_kek: bytes,
    ) -> bytes:
        """Unlock the DEK via the recovery key, rewrap the password side with
        ``new_h_kek``, clear the dek_recovery_required flag, and return the
        plaintext DEK.

        Raises :class:`DekUnlockError` on authentication failure.
        Raises :class:`UserKeyNotFoundError` if the user has no key document.
        """
        doc = await self._require_keys_doc(user_id)
        version = str(doc.current_dek_version)
        wrapped_by_recovery = doc.deks[version].wrapped_by_recovery

        key_rec = derive_wrap_key(decode_recovery_key(recovery_key), info=b"dek-wrap")
        try:
            dek = aes_gcm_unwrap(key_rec, wrapped_by_recovery)
        except AesGcmUnwrapError as exc:
            raise DekUnlockError("Recovery key did not authenticate the wrapped DEK") from exc

        # Rewrap password side only.
        key_pw_new = derive_wrap_key(new_h_kek, info=b"dek-wrap")
        new_wrapped_by_password = aes_gcm_wrap(key_pw_new, dek)

        await self._repo.replace_wrapped_by_password(
            user_id, version=doc.current_dek_version, blob=new_wrapped_by_password
        )
        await self._repo.set_recovery_required(user_id, value=False)

        return dek

    async def rewrap_password(
        self,
        *,
        user_id: str,
        h_kek_old: bytes,
        h_kek_new: bytes,
    ) -> bytes:
        """Unlock with the old password KEK and rewrap the password side only.

        The recovery-wrapped blob is left untouched. Returns the plaintext DEK.

        Raises :class:`DekUnlockError` on authentication failure with the old key.
        Raises :class:`UserKeyNotFoundError` if the user has no key document.
        """
        dek = await self.unlock_with_password(user_id=user_id, h_kek=h_kek_old)

        doc = await self._require_keys_doc(user_id)
        key_pw_new = derive_wrap_key(h_kek_new, info=b"dek-wrap")
        new_wrapped_by_password = aes_gcm_wrap(key_pw_new, dek)

        await self._repo.replace_wrapped_by_password(
            user_id, version=doc.current_dek_version, blob=new_wrapped_by_password
        )
        return dek

    # ------------------------------------------------------------------
    # Redis session-DEK store
    # ------------------------------------------------------------------

    async def store_session_dek(
        self, *, session_id: str, dek: bytes, ttl_seconds: int
    ) -> None:
        """Store ``dek`` in Redis under the session key with a TTL."""
        key = _SESSION_DEK_PREFIX + session_id
        await self._redis.set(key, dek, ex=ttl_seconds)

    async def fetch_session_dek(self, session_id: str) -> bytes | None:
        """Retrieve the session DEK from Redis, or None if absent / expired."""
        key = _SESSION_DEK_PREFIX + session_id
        return await self._redis.get(key)

    async def extend_session_dek_ttl(
        self, session_id: str, ttl_seconds: int
    ) -> bool:
        """Reset the TTL on an existing session DEK. Returns True if the key existed."""
        key = _SESSION_DEK_PREFIX + session_id
        return bool(await self._redis.expire(key, ttl_seconds))

    async def delete_session_dek(self, session_id: str) -> None:
        """Delete the session DEK from Redis (logout / revocation)."""
        key = _SESSION_DEK_PREFIX + session_id
        await self._redis.delete(key)

    # ------------------------------------------------------------------
    # Recovery flag
    # ------------------------------------------------------------------

    async def mark_recovery_required(self, user_id: str) -> None:
        """Set dek_recovery_required=True for a user (e.g. after failed unlock)."""
        await self._repo.set_recovery_required(user_id, value=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _require_keys_doc(self, user_id: str) -> UserKeysDocument:
        """Return the key document or raise :class:`UserKeyNotFoundError`."""
        doc = await self._repo.get_by_user_id(user_id)
        if doc is None:
            raise UserKeyNotFoundError(f"No key document found for user {user_id!r}")
        return doc
