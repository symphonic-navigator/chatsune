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
