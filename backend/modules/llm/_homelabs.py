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
        self, user_id: str, display_name: str
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
    ) -> dict:
        set_fields: dict = {}
        if display_name is not None:
            set_fields["display_name"] = display_name
        if allowed_model_slugs is not None:
            set_fields["allowed_model_slugs"] = list(allowed_model_slugs)
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


from shared.dtos.llm import ApiKeyDto, HomelabDto, HomelabEngineInfoDto
from shared.events.llm import (
    ApiKeyCreatedEvent,
    ApiKeyRevokedEvent,
    ApiKeyUpdatedEvent,
    HomelabCreatedEvent,
    HomelabDeletedEvent,
    HomelabHostKeyRegeneratedEvent,
    HomelabUpdatedEvent,
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
    )


def _now() -> datetime:
    return datetime.now(UTC)


class HomelabService:
    def __init__(self, db: AsyncIOMotorDatabase, event_bus) -> None:
        self._homelabs = HomelabRepository(db)
        self._keys = ApiKeyRepository(db)
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

    async def create_homelab(
        self, user_id: str, display_name: str
    ) -> dict:
        doc, plaintext = await self._homelabs.create(user_id, display_name)
        dto = _homelab_doc_to_dto(doc)
        await self._bus.publish(
            Topics.LLM_HOMELAB_CREATED,
            HomelabCreatedEvent(homelab=dto, timestamp=_now()),
            target_user_ids=[user_id],
        )
        return {"homelab": dto.model_dump(), "plaintext_host_key": plaintext}

    async def rename_homelab(
        self, user_id: str, homelab_id: str, display_name: str
    ) -> HomelabDto:
        doc = await self._homelabs.rename(user_id, homelab_id, display_name)
        dto = _homelab_doc_to_dto(doc)
        await self._bus.publish(
            Topics.LLM_HOMELAB_UPDATED,
            HomelabUpdatedEvent(homelab=dto, timestamp=_now()),
            target_user_ids=[user_id],
        )
        return dto

    async def delete_homelab(self, user_id: str, homelab_id: str) -> None:
        # ensure ownership
        await self._homelabs.get(user_id, homelab_id)
        await self._keys.delete_for_homelab(homelab_id)
        await self._homelabs.delete(user_id, homelab_id)
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
    ) -> dict:
        await self._homelabs.get(user_id, homelab_id)  # ownership check
        doc, plaintext = await self._keys.create(
            user_id=user_id,
            homelab_id=homelab_id,
            display_name=display_name,
            allowed_model_slugs=allowed_model_slugs,
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
    ) -> ApiKeyDto:
        await self._homelabs.get(user_id, homelab_id)
        doc = await self._keys.update(
            user_id=user_id,
            homelab_id=homelab_id,
            api_key_id=api_key_id,
            display_name=display_name,
            allowed_model_slugs=allowed_model_slugs,
        )
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
