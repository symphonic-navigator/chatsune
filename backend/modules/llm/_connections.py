"""Connection repository — per-user LLM backend instances."""

from __future__ import annotations

import logging
import re as _re
from datetime import UTC, datetime
from uuid import uuid4

from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.config import settings
from backend.modules.llm._registry import ADAPTER_REGISTRY
from shared.dtos.llm import ConnectionDto

_log = logging.getLogger(__name__)

_SLUG_RE = _re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _fernet() -> Fernet:
    return Fernet(settings.encryption_key.encode())


def _encrypt(v: str) -> str:
    return _fernet().encrypt(v.encode()).decode()


def _decrypt(v: str) -> str:
    return _fernet().decrypt(v.encode()).decode()


class InvalidSlugError(ValueError):
    pass


class InvalidAdapterTypeError(ValueError):
    pass


class SlugAlreadyExistsError(ValueError):
    def __init__(self, slug: str, suggested: str) -> None:
        super().__init__(f"Slug '{slug}' already exists")
        self.slug = slug
        self.suggested = suggested


RESERVED_SLUGS: frozenset[str] = frozenset({"xai", "mistral", "ollama_cloud"})


class SlugReservedError(ValueError):
    """Slug is reserved for a Premium Provider and cannot be user-created."""

    def __init__(self, slug: str) -> None:
        super().__init__(f"Slug '{slug}' is reserved for a Premium Provider")
        self.slug = slug


class ConnectionNotFoundError(KeyError):
    pass


class ConnectionSystemManagedError(ValueError):
    """Raised when a caller attempts to edit or delete a system-managed Connection.

    System-managed connections are lifecycle-owned by another module (e.g. the
    host-self Connection mirrored from a Homelab). Callers inside the owning
    module use the ``*_by_system`` variants to bypass this check.
    """
    pass


def _validate_slug(slug: str) -> None:
    if slug in RESERVED_SLUGS:
        raise SlugReservedError(slug)
    if not _SLUG_RE.match(slug):
        raise InvalidSlugError(
            f"Slug '{slug}' must be lowercase alphanumeric with hyphens, 1-63 chars"
        )


def _split_config(adapter_type: str, config: dict) -> tuple[dict, dict]:
    adapter_cls = ADAPTER_REGISTRY.get(adapter_type)
    if adapter_cls is None:
        raise InvalidAdapterTypeError(adapter_type)
    plain: dict = {}
    encrypted: dict = {}
    for k, v in config.items():
        if k in adapter_cls.secret_fields:
            if v is None or v == "":
                continue
            encrypted[k] = _encrypt(str(v))
        else:
            plain[k] = v
    return plain, encrypted


def _redact_config(adapter_type: str, plain: dict, encrypted: dict) -> dict:
    adapter_cls = ADAPTER_REGISTRY.get(adapter_type)
    secret_fields = adapter_cls.secret_fields if adapter_cls else frozenset()
    out = dict(plain)
    for k in secret_fields:
        out[k] = {"is_set": k in encrypted}
    return out


class ConnectionRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db["llm_connections"]

    async def create_indexes(self) -> None:
        await self._col.create_index([("user_id", 1), ("slug", 1)], unique=True)
        await self._col.create_index([("user_id", 1), ("created_at", 1)])

    async def suggest_slug(self, user_id: str, base: str) -> str:
        _validate_slug(base)
        existing = {
            doc["slug"]
            async for doc in self._col.find({"user_id": user_id}, {"slug": 1})
        }
        if base not in existing:
            return base
        n = 2
        while f"{base}-{n}" in existing:
            n += 1
        return f"{base}-{n}"

    async def create(
        self,
        user_id: str,
        adapter_type: str,
        display_name: str,
        slug: str,
        config: dict,
        *,
        is_system_managed: bool = False,
    ) -> dict:
        _validate_slug(slug)
        if adapter_type not in ADAPTER_REGISTRY:
            raise InvalidAdapterTypeError(adapter_type)
        if await self._col.find_one({"user_id": user_id, "slug": slug}):
            suggested = await self.suggest_slug(user_id, slug)
            raise SlugAlreadyExistsError(slug, suggested)
        plain, encrypted = _split_config(adapter_type, config)
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "adapter_type": adapter_type,
            "display_name": display_name,
            "slug": slug,
            "config": plain,
            "config_encrypted": encrypted,
            "last_test_status": None,
            "last_test_error": None,
            "last_test_at": None,
            "created_at": now,
            "updated_at": now,
            "is_system_managed": bool(is_system_managed),
        }
        await self._col.insert_one(doc)
        return doc

    async def find(self, user_id: str, connection_id: str) -> dict | None:
        return await self._col.find_one(
            {"_id": connection_id, "user_id": user_id}
        )

    async def find_by_slug(self, user_id: str, slug: str) -> dict | None:
        return await self._col.find_one(
            {"slug": slug, "user_id": user_id}
        )

    async def find_any(self, connection_id: str) -> dict | None:
        """Owner-agnostic lookup — use only for internal tracker enrichment."""
        return await self._col.find_one({"_id": connection_id})

    async def list_for_user(self, user_id: str) -> list[dict]:
        return [
            d async for d in self._col.find({"user_id": user_id}).sort("created_at", 1)
        ]

    async def update(
        self,
        user_id: str,
        connection_id: str,
        display_name: str | None = None,
        slug: str | None = None,
        config: dict | None = None,
    ) -> dict:
        doc = await self.find(user_id, connection_id)
        if doc is None:
            raise ConnectionNotFoundError(connection_id)
        if doc.get("is_system_managed", False):
            raise ConnectionSystemManagedError(connection_id)
        return await self._do_update(doc, display_name, slug, config)

    async def update_by_system(
        self,
        user_id: str,
        connection_id: str,
        display_name: str | None = None,
        slug: str | None = None,
        config: dict | None = None,
    ) -> dict:
        """Internal-only variant that bypasses the ``is_system_managed`` guard.

        Use from the module that owns the system-managed connection's
        lifecycle (e.g. :class:`HomelabService`).
        """
        doc = await self.find(user_id, connection_id)
        if doc is None:
            raise ConnectionNotFoundError(connection_id)
        return await self._do_update(doc, display_name, slug, config)

    async def _do_update(
        self,
        doc: dict,
        display_name: str | None,
        slug: str | None,
        config: dict | None,
    ) -> dict:
        user_id = doc["user_id"]
        connection_id = doc["_id"]

        slug_changed = slug is not None and slug != doc["slug"]
        update_payload: dict = {"updated_at": datetime.now(UTC)}
        if display_name is not None:
            update_payload["display_name"] = display_name
        if slug_changed:
            _validate_slug(slug)
            dup = await self._col.find_one(
                {"user_id": user_id, "slug": slug, "_id": {"$ne": connection_id}}
            )
            if dup:
                suggested = await self.suggest_slug(user_id, slug)
                raise SlugAlreadyExistsError(slug, suggested)
            update_payload["slug"] = slug
        if config is not None:
            plain, encrypted = _split_config(doc["adapter_type"], config)
            # Merge semantics for secrets: a secret field that is *absent* from
            # the incoming config means "leave the existing value alone" — not
            # "wipe it". A secret field present with an empty/None value is the
            # explicit-clear case (handled inside `_split_config` by skipping it
            # from `encrypted`; we additionally drop the existing encrypted value
            # here so the clear actually takes effect).
            adapter_cls = ADAPTER_REGISTRY.get(doc["adapter_type"])
            secret_fields = (
                adapter_cls.secret_fields if adapter_cls else frozenset()
            )
            merged_encrypted = dict(doc.get("config_encrypted", {}))
            for field in secret_fields:
                if field in encrypted:
                    # New plaintext provided — replace.
                    merged_encrypted[field] = encrypted[field]
                elif field in config and (
                    config[field] is None or config[field] == ""
                ):
                    # Explicit clear.
                    merged_encrypted.pop(field, None)
                # Otherwise field absent from incoming config → preserve.
            update_payload["config"] = plain
            update_payload["config_encrypted"] = merged_encrypted

        if not slug_changed:
            # Fast path — single-document update, no cascade needed.
            return await self._col.find_one_and_update(
                {"_id": connection_id, "user_id": user_id},
                {"$set": update_payload},
                return_document=True,
            )

        # Slug changed — run connection update + cascade in a single transaction
        # so that no document is left referencing the old slug if a step fails.
        old_slug = doc["slug"]
        client = self._col.database.client
        async with await client.start_session() as session:
            async with session.start_transaction():
                await self._col.update_one(
                    {"_id": connection_id, "user_id": user_id},
                    {"$set": update_payload},
                    session=session,
                )
                await self._cascade_unique_id_prefix(
                    session, "personas", user_id, old_slug, slug,
                )
                await self._cascade_unique_id_prefix(
                    session, "llm_user_model_configs", user_id, old_slug, slug,
                )
        return await self.find(user_id, connection_id)

    async def _cascade_unique_id_prefix(
        self,
        session,
        collection: str,
        user_id: str,
        old_slug: str,
        new_slug: str,
    ) -> None:
        """Update model_unique_id for every document in *collection* whose
        model_unique_id starts with ``old_slug:`` and belongs to *user_id*."""
        col = self._col.database[collection]
        prefix_pattern = f"^{_re.escape(old_slug)}:"
        cursor = col.find(
            {"user_id": user_id, "model_unique_id": {"$regex": prefix_pattern}},
            session=session,
        )
        async for doc in cursor:
            suffix = doc["model_unique_id"].split(":", 1)[1]
            await col.update_one(
                {"_id": doc["_id"]},
                {"$set": {"model_unique_id": f"{new_slug}:{suffix}"}},
                session=session,
            )

    async def delete(self, user_id: str, connection_id: str) -> bool:
        doc = await self.find(user_id, connection_id)
        if doc is None:
            return False
        if doc.get("is_system_managed", False):
            raise ConnectionSystemManagedError(connection_id)
        result = await self._col.delete_one(
            {"_id": connection_id, "user_id": user_id}
        )
        return result.deleted_count > 0

    async def delete_by_system(self, user_id: str, connection_id: str) -> bool:
        """Internal-only variant that bypasses the ``is_system_managed`` guard."""
        result = await self._col.delete_one(
            {"_id": connection_id, "user_id": user_id}
        )
        return result.deleted_count > 0

    async def list_ids_for_user(self, user_id: str) -> list[str]:
        """Return every connection ``_id`` owned by ``user_id``.

        Used by the user self-delete cascade to compute the set of
        ``llm:models:{connection_id}`` cache keys that need clearing
        BEFORE the connection rows themselves are removed.
        """
        cursor = self._col.find({"user_id": user_id}, {"_id": 1})
        return [d["_id"] async for d in cursor]

    async def delete_all_for_user(self, user_id: str) -> int:
        """Delete every connection owned by ``user_id``. Returns the deleted count.

        Used by the user self-delete cascade (right-to-be-forgotten).
        """
        result = await self._col.delete_many({"user_id": user_id})
        return result.deleted_count

    async def update_test_status(
        self,
        user_id: str,
        connection_id: str,
        *,
        status: str,
        error: str | None,
    ) -> dict | None:
        now = datetime.now(UTC)
        return await self._col.find_one_and_update(
            {"_id": connection_id, "user_id": user_id},
            {
                "$set": {
                    "last_test_status": status,
                    "last_test_error": error,
                    "last_test_at": now,
                    "updated_at": now,
                }
            },
            return_document=True,
        )

    @staticmethod
    def to_dto(doc: dict) -> ConnectionDto:
        return ConnectionDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            adapter_type=doc["adapter_type"],
            display_name=doc["display_name"],
            slug=doc["slug"],
            config=_redact_config(
                doc["adapter_type"],
                doc.get("config", {}),
                doc.get("config_encrypted", {}),
            ),
            last_test_status=doc.get("last_test_status"),
            last_test_error=doc.get("last_test_error"),
            last_test_at=doc.get("last_test_at"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            is_system_managed=bool(doc.get("is_system_managed", False)),
        )

    @staticmethod
    def get_decrypted_secret(doc: dict, field: str) -> str | None:
        enc = doc.get("config_encrypted", {})
        if field not in enc:
            return None
        return _decrypt(enc[field])
