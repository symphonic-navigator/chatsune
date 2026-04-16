"""Host-side community provisioning: homelabs and their api-keys."""

from __future__ import annotations

import logging
import secrets as _secrets
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.llm._homelab_tokens import (
    generate_api_key,
    generate_homelab_id,
    generate_host_key,
    hash_token,
    hint_for,
)

_log = logging.getLogger(__name__)


class HomelabNotFoundError(KeyError):
    pass


class ApiKeyNotFoundError(KeyError):
    pass


class TooManyHomelabsError(RuntimeError):
    pass


class TooManyApiKeysError(RuntimeError):
    pass


class HostSlugAlreadyExistsError(ValueError):
    def __init__(self, slug: str, suggested: str) -> None:
        super().__init__(f"Host slug '{slug}' is already used by another connection")
        self.slug = slug
        self.suggested = suggested


class HomelabRepository:
    def __init__(
        self, db: AsyncIOMotorDatabase, max_per_user: int = 10
    ) -> None:
        self._col = db["llm_homelabs"]
        self._max_per_user = max_per_user

    async def create_indexes(self) -> None:
        await self._col.create_index("homelab_id", unique=True)
        await self._col.create_index("host_key_hash", unique=True)
        await self._col.create_index([("user_id", 1), ("created_at", 1)])

    async def create(
        self,
        user_id: str,
        display_name: str,
        host_slug: str | None = None,
        max_concurrent_requests: int = 3,
    ) -> tuple[dict, str]:
        count = await self._col.count_documents({"user_id": user_id})
        if count >= self._max_per_user:
            raise TooManyHomelabsError(
                f"User {user_id} already has {count} homelabs (max {self._max_per_user})"
            )
        plaintext = generate_host_key()
        now = datetime.now(UTC)
        doc = {
            "user_id": user_id,
            "homelab_id": generate_homelab_id(),
            "display_name": display_name,
            "host_key_hash": hash_token(plaintext),
            "host_key_hint": hint_for(plaintext),
            "status": "active",
            "created_at": now,
            "last_seen_at": None,
            "last_sidecar_version": None,
            "last_engine_info": None,
            "max_concurrent_requests": max_concurrent_requests,
            "host_slug": host_slug,
        }
        await self._col.insert_one(doc)
        return doc, plaintext

    async def list(self, user_id: str) -> list[dict]:
        cursor = self._col.find({"user_id": user_id}).sort("created_at", 1)
        return [doc async for doc in cursor]

    async def get(self, user_id: str, homelab_id: str) -> dict:
        doc = await self._col.find_one(
            {"user_id": user_id, "homelab_id": homelab_id}
        )
        if doc is None:
            raise HomelabNotFoundError(homelab_id)
        return doc

    async def rename(
        self, user_id: str, homelab_id: str, display_name: str
    ) -> dict:
        res = await self._col.find_one_and_update(
            {"user_id": user_id, "homelab_id": homelab_id},
            {"$set": {"display_name": display_name}},
            return_document=True,
        )
        if res is None:
            raise HomelabNotFoundError(homelab_id)
        return res

    async def update(
        self,
        user_id: str,
        homelab_id: str,
        display_name: str | None = None,
        max_concurrent_requests: int | None = None,
    ) -> dict:
        set_fields: dict = {}
        if display_name is not None:
            set_fields["display_name"] = display_name
        if max_concurrent_requests is not None:
            set_fields["max_concurrent_requests"] = max_concurrent_requests
        if not set_fields:
            return await self.get(user_id, homelab_id)
        res = await self._col.find_one_and_update(
            {"user_id": user_id, "homelab_id": homelab_id},
            {"$set": set_fields},
            return_document=True,
        )
        if res is None:
            raise HomelabNotFoundError(homelab_id)
        return res

    async def find_by_id(self, homelab_id: str) -> dict | None:
        """Owner-agnostic lookup — used by the consumer path where the caller
        is not the homelab owner but still needs the homelab's config
        (e.g. ``max_concurrent_requests``).
        """
        return await self._col.find_one({"homelab_id": homelab_id})

    async def delete(self, user_id: str, homelab_id: str) -> None:
        res = await self._col.delete_one(
            {"user_id": user_id, "homelab_id": homelab_id}
        )
        if res.deleted_count == 0:
            raise HomelabNotFoundError(homelab_id)

    async def regenerate_host_key(
        self, user_id: str, homelab_id: str
    ) -> tuple[dict, str]:
        plaintext = generate_host_key()
        res = await self._col.find_one_and_update(
            {"user_id": user_id, "homelab_id": homelab_id},
            {
                "$set": {
                    "host_key_hash": hash_token(plaintext),
                    "host_key_hint": hint_for(plaintext),
                }
            },
            return_document=True,
        )
        if res is None:
            raise HomelabNotFoundError(homelab_id)
        return res, plaintext

    async def find_by_host_key_hash(self, host_key_hash: str) -> dict | None:
        return await self._col.find_one(
            {"host_key_hash": host_key_hash, "status": "active"}
        )

    async def touch_last_seen(
        self,
        homelab_id: str,
        sidecar_version: str | None,
        engine_info: dict | None,
    ) -> None:
        await self._col.update_one(
            {"homelab_id": homelab_id},
            {
                "$set": {
                    "last_seen_at": datetime.now(UTC),
                    "last_sidecar_version": sidecar_version,
                    "last_engine_info": engine_info,
                }
            },
        )


class ApiKeyRepository:
    def __init__(
        self, db: AsyncIOMotorDatabase, max_per_homelab: int = 50
    ) -> None:
        self._col = db["llm_homelab_api_keys"]
        self._max_per_homelab = max_per_homelab

    async def create_indexes(self) -> None:
        await self._col.create_index("api_key_hash", unique=True)
        await self._col.create_index([("homelab_id", 1), ("created_at", 1)])

    async def create(
        self,
        user_id: str,
        homelab_id: str,
        display_name: str,
        allowed_model_slugs: list[str],
        max_concurrent: int = 1,
    ) -> tuple[dict, str]:
        count = await self._col.count_documents({"homelab_id": homelab_id})
        if count >= self._max_per_homelab:
            raise TooManyApiKeysError(
                f"Homelab {homelab_id} already has {count} api-keys (max {self._max_per_homelab})"
            )
        plaintext = generate_api_key()
        now = datetime.now(UTC)
        doc = {
            "homelab_id": homelab_id,
            "user_id": user_id,
            "api_key_id": _secrets.token_urlsafe(8),
            "display_name": display_name,
            "api_key_hash": hash_token(plaintext),
            "api_key_hint": hint_for(plaintext),
            "allowed_model_slugs": list(allowed_model_slugs),
            "status": "active",
            "created_at": now,
            "revoked_at": None,
            "last_used_at": None,
            "max_concurrent": max_concurrent,
        }
        await self._col.insert_one(doc)
        return doc, plaintext

    async def list(self, homelab_id: str) -> list[dict]:
        cursor = self._col.find({"homelab_id": homelab_id}).sort("created_at", 1)
        return [doc async for doc in cursor]

    async def get(
        self, user_id: str, homelab_id: str, api_key_id: str
    ) -> dict:
        doc = await self._col.find_one(
            {
                "user_id": user_id,
                "homelab_id": homelab_id,
                "api_key_id": api_key_id,
            }
        )
        if doc is None:
            raise ApiKeyNotFoundError(api_key_id)
        return doc

    async def update(
        self,
        user_id: str,
        homelab_id: str,
        api_key_id: str,
        display_name: str | None = None,
        allowed_model_slugs: list[str] | None = None,
        max_concurrent: int | None = None,
    ) -> dict:
        set_fields: dict = {}
        if display_name is not None:
            set_fields["display_name"] = display_name
        if allowed_model_slugs is not None:
            set_fields["allowed_model_slugs"] = list(allowed_model_slugs)
        if max_concurrent is not None:
            set_fields["max_concurrent"] = max_concurrent
        if not set_fields:
            return await self.get(user_id, homelab_id, api_key_id)
        res = await self._col.find_one_and_update(
            {
                "user_id": user_id,
                "homelab_id": homelab_id,
                "api_key_id": api_key_id,
            },
            {"$set": set_fields},
            return_document=True,
        )
        if res is None:
            raise ApiKeyNotFoundError(api_key_id)
        return res

    async def revoke(
        self, user_id: str, homelab_id: str, api_key_id: str
    ) -> dict:
        now = datetime.now(UTC)
        res = await self._col.find_one_and_update(
            {
                "user_id": user_id,
                "homelab_id": homelab_id,
                "api_key_id": api_key_id,
            },
            {"$set": {"status": "revoked", "revoked_at": now}},
            return_document=True,
        )
        if res is None:
            raise ApiKeyNotFoundError(api_key_id)
        return res

    async def regenerate(
        self, user_id: str, homelab_id: str, api_key_id: str
    ) -> tuple[dict, str]:
        plaintext = generate_api_key()
        res = await self._col.find_one_and_update(
            {
                "user_id": user_id,
                "homelab_id": homelab_id,
                "api_key_id": api_key_id,
            },
            {
                "$set": {
                    "api_key_hash": hash_token(plaintext),
                    "api_key_hint": hint_for(plaintext),
                    "status": "active",
                    "revoked_at": None,
                }
            },
            return_document=True,
        )
        if res is None:
            raise ApiKeyNotFoundError(api_key_id)
        return res, plaintext

    async def find_active_by_hash(
        self, homelab_id: str, api_key_hash: str
    ) -> dict | None:
        return await self._col.find_one(
            {
                "homelab_id": homelab_id,
                "api_key_hash": api_key_hash,
                "status": "active",
            }
        )

    async def delete_for_homelab(self, homelab_id: str) -> int:
        res = await self._col.delete_many({"homelab_id": homelab_id})
        return res.deleted_count


from backend.modules.llm._connections import ConnectionRepository
from backend.modules.llm._homelab_semaphores import (
    get_api_key_semaphore_registry,
    get_homelab_semaphore_registry,
)
from backend.modules.llm._semaphores import get_semaphore_registry
from shared.dtos.llm import ApiKeyDto, HomelabDto, HomelabEngineInfoDto
from shared.events.llm import (
    ApiKeyCreatedEvent,
    ApiKeyRevokedEvent,
    ApiKeyUpdatedEvent,
    HomelabCreatedEvent,
    HomelabDeletedEvent,
    HomelabHostKeyRegeneratedEvent,
    HomelabUpdatedEvent,
    LlmConnectionCreatedEvent,
    LlmConnectionRemovedEvent,
    LlmConnectionUpdatedEvent,
)
from shared.topics import Topics


def _homelab_doc_to_dto(doc: dict, is_online: bool = False) -> HomelabDto:
    engine_info = None
    if doc.get("last_engine_info"):
        engine_info = HomelabEngineInfoDto(**doc["last_engine_info"])
    return HomelabDto(
        homelab_id=doc["homelab_id"],
        display_name=doc["display_name"],
        host_key_hint=doc["host_key_hint"],
        status=doc["status"],
        created_at=doc["created_at"],
        last_seen_at=doc.get("last_seen_at"),
        last_sidecar_version=doc.get("last_sidecar_version"),
        last_engine_info=engine_info,
        is_online=is_online,
        max_concurrent_requests=int(doc.get("max_concurrent_requests", 3)),
        host_slug=doc.get("host_slug"),
    )


def _api_key_doc_to_dto(doc: dict) -> ApiKeyDto:
    return ApiKeyDto(
        api_key_id=doc["api_key_id"],
        homelab_id=doc["homelab_id"],
        display_name=doc["display_name"],
        api_key_hint=doc["api_key_hint"],
        allowed_model_slugs=list(doc.get("allowed_model_slugs", [])),
        status=doc["status"],
        created_at=doc["created_at"],
        revoked_at=doc.get("revoked_at"),
        last_used_at=doc.get("last_used_at"),
        max_concurrent=int(doc.get("max_concurrent", 1)),
    )


def _now() -> datetime:
    return datetime.now(UTC)


class HomelabService:
    def __init__(self, db: AsyncIOMotorDatabase, event_bus) -> None:
        self._homelabs = HomelabRepository(db)
        self._keys = ApiKeyRepository(db)
        self._connections = ConnectionRepository(db)
        self._bus = event_bus

    async def init(self) -> None:
        await self._homelabs.create_indexes()
        await self._keys.create_indexes()

    # --- Homelab ops

    async def list_homelabs(
        self, user_id: str, online_ids: set[str] | None = None
    ) -> list[HomelabDto]:
        docs = await self._homelabs.list(user_id)
        online_ids = online_ids or set()
        return [
            _homelab_doc_to_dto(d, is_online=d["homelab_id"] in online_ids)
            for d in docs
        ]

    async def get_homelab(
        self, user_id: str, homelab_id: str, is_online: bool = False
    ) -> HomelabDto:
        doc = await self._homelabs.get(user_id, homelab_id)
        return _homelab_doc_to_dto(doc, is_online=is_online)

    async def find_homelab_by_id(self, homelab_id: str) -> dict | None:
        """Owner-agnostic lookup — used by the consumer path in the adapter."""
        return await self._homelabs.find_by_id(homelab_id)

    async def create_homelab(
        self,
        user_id: str,
        display_name: str,
        host_slug: str,
        max_concurrent_requests: int = 3,
    ) -> dict:
        # Reserve the slug check before inserting anything; this is the
        # best-effort guard before the actual self-connection insert (which
        # also enforces uniqueness via a unique index).
        existing = await self._connections.find_by_slug(user_id, host_slug)
        if existing is not None:
            suggested = await self._connections.suggest_slug(user_id, host_slug)
            raise HostSlugAlreadyExistsError(host_slug, suggested)

        homelab_doc, plaintext = await self._homelabs.create(
            user_id=user_id,
            display_name=display_name,
            host_slug=host_slug,
            max_concurrent_requests=max_concurrent_requests,
        )
        homelab_id = homelab_doc["homelab_id"]

        # Create the system-managed self-connection. On failure we roll back
        # the homelab doc so we never leave a homelab without its self-connection.
        try:
            conn_doc = await self._connections.create(
                user_id=user_id,
                adapter_type="community",
                display_name=display_name,
                slug=host_slug,
                config={
                    "homelab_id": homelab_id,
                    "is_host_self": True,
                    "max_parallel": max_concurrent_requests,
                },
                is_system_managed=True,
            )
        except Exception:
            try:
                await self._homelabs.delete(user_id, homelab_id)
            except Exception:  # noqa: BLE001 — best-effort rollback
                _log.warning(
                    "create_homelab.rollback_failed homelab_id=%s", homelab_id,
                )
            raise

        homelab_dto = _homelab_doc_to_dto(homelab_doc)
        await self._bus.publish(
            Topics.LLM_HOMELAB_CREATED,
            HomelabCreatedEvent(homelab=homelab_dto, timestamp=_now()),
            target_user_ids=[user_id],
        )
        conn_dto = ConnectionRepository.to_dto(conn_doc)
        await self._bus.publish(
            Topics.LLM_CONNECTION_CREATED,
            LlmConnectionCreatedEvent(connection=conn_dto, timestamp=_now()),
            target_user_ids=[user_id],
        )
        return {
            "homelab": homelab_dto.model_dump(),
            "plaintext_host_key": plaintext,
            "self_connection_id": conn_doc["_id"],
        }

    async def update_homelab(
        self,
        user_id: str,
        homelab_id: str,
        display_name: str | None = None,
        max_concurrent_requests: int | None = None,
    ) -> HomelabDto:
        """Update the display_name and/or max_concurrent_requests of a homelab.

        Cascades to the self-connection: renames it and rewrites
        ``config.max_parallel`` so the per-connection semaphore picks up the
        new cap on the next request.
        """
        before = await self._homelabs.get(user_id, homelab_id)
        doc = await self._homelabs.update(
            user_id=user_id,
            homelab_id=homelab_id,
            display_name=display_name,
            max_concurrent_requests=max_concurrent_requests,
        )
        dto = _homelab_doc_to_dto(doc)
        await self._bus.publish(
            Topics.LLM_HOMELAB_UPDATED,
            HomelabUpdatedEvent(homelab=dto, timestamp=_now()),
            target_user_ids=[user_id],
        )

        # Sync the self-connection, if any. Keyed by host_slug which is the
        # connection's slug; use find_by_slug to locate it.
        host_slug = before.get("host_slug")
        if host_slug:
            conn = await self._connections.find_by_slug(user_id, host_slug)
            if conn is not None and conn.get("is_system_managed"):
                new_display = (
                    display_name
                    if display_name is not None and display_name != before["display_name"]
                    else None
                )
                new_max = (
                    max_concurrent_requests
                    if max_concurrent_requests is not None
                    and max_concurrent_requests != int(before.get("max_concurrent_requests", 3))
                    else None
                )
                if new_display is not None or new_max is not None:
                    new_config: dict | None = None
                    if new_max is not None:
                        merged_config = dict(conn.get("config", {}))
                        merged_config["max_parallel"] = new_max
                        # is_host_self / homelab_id must be preserved — they're
                        # already in the existing config so the merged dict is
                        # complete.
                        new_config = merged_config
                    updated_conn = await self._connections.update_by_system(
                        user_id=user_id,
                        connection_id=conn["_id"],
                        display_name=new_display,
                        config=new_config,
                    )
                    # Evict per-connection semaphore so the new max_parallel
                    # takes effect on the next request.
                    get_semaphore_registry().evict(conn["_id"])
                    conn_dto = ConnectionRepository.to_dto(updated_conn)
                    await self._bus.publish(
                        Topics.LLM_CONNECTION_UPDATED,
                        LlmConnectionUpdatedEvent(
                            connection=conn_dto, timestamp=_now(),
                        ),
                        target_user_ids=[user_id],
                    )

        # Rebuild the homelab-wide semaphore if the cap changed.
        if (
            max_concurrent_requests is not None
            and max_concurrent_requests != int(before.get("max_concurrent_requests", 3))
        ):
            get_homelab_semaphore_registry().evict(homelab_id)

        return dto

    # Backwards-compat alias — existing call sites (and tests) use rename_homelab.
    async def rename_homelab(
        self, user_id: str, homelab_id: str, display_name: str
    ) -> HomelabDto:
        return await self.update_homelab(
            user_id=user_id,
            homelab_id=homelab_id,
            display_name=display_name,
        )

    async def delete_homelab(self, user_id: str, homelab_id: str) -> None:
        # ensure ownership
        doc = await self._homelabs.get(user_id, homelab_id)

        # Collect api-key IDs first so we can evict their semaphore entries.
        api_keys = await self._keys.list(homelab_id=homelab_id)
        api_key_ids = [k["api_key_id"] for k in api_keys]

        await self._keys.delete_for_homelab(homelab_id)

        # Delete the self-connection (if any). Use the system-bypass variant.
        host_slug = doc.get("host_slug")
        self_connection_id: str | None = None
        if host_slug:
            conn = await self._connections.find_by_slug(user_id, host_slug)
            if conn is not None and conn.get("is_system_managed"):
                self_connection_id = conn["_id"]
                await self._connections.delete_by_system(user_id, conn["_id"])

        await self._homelabs.delete(user_id, homelab_id)

        # Evict process-local semaphore registry entries.
        get_homelab_semaphore_registry().evict(homelab_id)
        api_key_sem = get_api_key_semaphore_registry()
        for kid in api_key_ids:
            api_key_sem.evict(kid)
        if self_connection_id is not None:
            get_semaphore_registry().evict(self_connection_id)
            # Emit connection-removed so clients refresh their view.
            await self._bus.publish(
                Topics.LLM_CONNECTION_REMOVED,
                LlmConnectionRemovedEvent(
                    connection_id=self_connection_id,
                    affected_persona_ids=[],
                    timestamp=_now(),
                ),
                target_user_ids=[user_id],
            )

        await self._bus.publish(
            Topics.LLM_HOMELAB_DELETED,
            HomelabDeletedEvent(homelab_id=homelab_id, timestamp=_now()),
            target_user_ids=[user_id],
        )

    async def regenerate_host_key(
        self, user_id: str, homelab_id: str
    ) -> dict:
        doc, plaintext = await self._homelabs.regenerate_host_key(
            user_id, homelab_id
        )
        dto = _homelab_doc_to_dto(doc)
        await self._bus.publish(
            Topics.LLM_HOMELAB_HOST_KEY_REGENERATED,
            HomelabHostKeyRegeneratedEvent(homelab=dto, timestamp=_now()),
            target_user_ids=[user_id],
        )
        return {"homelab": dto.model_dump(), "plaintext_host_key": plaintext}

    # --- API-key ops

    async def list_api_keys(
        self, user_id: str, homelab_id: str
    ) -> list[ApiKeyDto]:
        await self._homelabs.get(user_id, homelab_id)  # ownership check
        docs = await self._keys.list(homelab_id=homelab_id)
        return [_api_key_doc_to_dto(d) for d in docs]

    async def create_api_key(
        self,
        user_id: str,
        homelab_id: str,
        display_name: str,
        allowed_model_slugs: list[str],
        max_concurrent: int = 1,
    ) -> dict:
        await self._homelabs.get(user_id, homelab_id)  # ownership check
        doc, plaintext = await self._keys.create(
            user_id=user_id,
            homelab_id=homelab_id,
            display_name=display_name,
            allowed_model_slugs=allowed_model_slugs,
            max_concurrent=max_concurrent,
        )
        dto = _api_key_doc_to_dto(doc)
        await self._bus.publish(
            Topics.LLM_API_KEY_CREATED,
            ApiKeyCreatedEvent(api_key=dto, timestamp=_now()),
            target_user_ids=[user_id],
        )
        return {"api_key": dto.model_dump(), "plaintext_api_key": plaintext}

    async def update_api_key(
        self,
        user_id: str,
        homelab_id: str,
        api_key_id: str,
        display_name: str | None,
        allowed_model_slugs: list[str] | None,
        max_concurrent: int | None = None,
    ) -> ApiKeyDto:
        await self._homelabs.get(user_id, homelab_id)
        doc = await self._keys.update(
            user_id=user_id,
            homelab_id=homelab_id,
            api_key_id=api_key_id,
            display_name=display_name,
            allowed_model_slugs=allowed_model_slugs,
            max_concurrent=max_concurrent,
        )
        if max_concurrent is not None:
            get_api_key_semaphore_registry().evict(api_key_id)
        dto = _api_key_doc_to_dto(doc)
        await self._bus.publish(
            Topics.LLM_API_KEY_UPDATED,
            ApiKeyUpdatedEvent(api_key=dto, timestamp=_now()),
            target_user_ids=[user_id],
        )
        return dto

    async def revoke_api_key(
        self, user_id: str, homelab_id: str, api_key_id: str
    ) -> None:
        await self._homelabs.get(user_id, homelab_id)
        await self._keys.revoke(user_id, homelab_id, api_key_id)
        get_api_key_semaphore_registry().evict(api_key_id)
        await self._bus.publish(
            Topics.LLM_API_KEY_REVOKED,
            ApiKeyRevokedEvent(
                api_key_id=api_key_id,
                homelab_id=homelab_id,
                timestamp=_now(),
            ),
            target_user_ids=[user_id],
        )

    async def regenerate_api_key(
        self, user_id: str, homelab_id: str, api_key_id: str
    ) -> dict:
        await self._homelabs.get(user_id, homelab_id)
        doc, plaintext = await self._keys.regenerate(
            user_id, homelab_id, api_key_id
        )
        get_api_key_semaphore_registry().evict(api_key_id)
        dto = _api_key_doc_to_dto(doc)
        await self._bus.publish(
            Topics.LLM_API_KEY_UPDATED,
            ApiKeyUpdatedEvent(api_key=dto, timestamp=_now()),
            target_user_ids=[user_id],
        )
        return {"api_key": dto.model_dump(), "plaintext_api_key": plaintext}

    # --- Sidecar-auth helpers (used later by CSP)

    async def touch_last_seen(
        self,
        homelab_id: str,
        sidecar_version: str | None,
        engine_info: dict | None,
    ) -> None:
        """Record the time of the last successful sidecar handshake.

        Called from the CSP endpoint every time a sidecar connects. Does
        not ownership-check ``homelab_id`` because the caller has already
        authenticated via the Host-Key.
        """
        await self._homelabs.touch_last_seen(
            homelab_id=homelab_id,
            sidecar_version=sidecar_version,
            engine_info=engine_info,
        )

    async def resolve_homelab_by_host_key(self, plaintext: str) -> dict | None:
        return await self._homelabs.find_by_host_key_hash(
            hash_token(plaintext)
        )

    async def validate_consumer_access(
        self, homelab_id: str, api_key_plaintext: str, model_slug: str
    ) -> dict | None:
        doc = await self._keys.find_active_by_hash(
            homelab_id=homelab_id, api_key_hash=hash_token(api_key_plaintext)
        )
        if doc is None:
            return None
        if model_slug not in doc["allowed_model_slugs"]:
            return None
        return doc

    async def validate_consumer_access_key(
        self, homelab_id: str, api_key_plaintext: str
    ) -> dict | None:
        """Verify an API-Key without a model-slug check.

        Used by the Community adapter to list models (per-model authorisation
        is then enforced by filtering against ``allowed_model_slugs``) and by
        the ``/test`` endpoint.
        """
        return await self._keys.find_active_by_hash(
            homelab_id=homelab_id,
            api_key_hash=hash_token(api_key_plaintext),
        )
