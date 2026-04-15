"""MongoDB persistence for per-user integration configurations."""

import logging
from motor.motor_asyncio import AsyncIOMotorDatabase

_log = logging.getLogger(__name__)

COLLECTION = "user_integration_configs"


class IntegrationRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self._col = db[COLLECTION]

    async def init_indexes(self) -> None:
        await self._col.create_index(
            [("user_id", 1), ("integration_id", 1)],
            unique=True,
        )

    async def get_user_configs(self, user_id: str) -> list[dict]:
        """Return all integration configs for a user."""
        cursor = self._col.find({"user_id": user_id}, {"_id": 0})
        return await cursor.to_list(length=100)

    async def get_user_config(self, user_id: str, integration_id: str) -> dict | None:
        """Return a single integration config."""
        return await self._col.find_one(
            {"user_id": user_id, "integration_id": integration_id},
            {"_id": 0},
        )

    async def delete_all_for_user(self, user_id: str) -> int:
        """Delete every integration config owned by ``user_id``.

        Used by the user self-delete cascade (right-to-be-forgotten).
        """
        res = await self._col.delete_many({"user_id": user_id})
        return res.deleted_count

    async def upsert_config(
        self,
        user_id: str,
        integration_id: str,
        enabled: bool,
        config: dict,
    ) -> dict:
        """Create or update a user's integration config."""
        doc = {
            "user_id": user_id,
            "integration_id": integration_id,
            "enabled": enabled,
            "config": config,
        }
        await self._col.update_one(
            {"user_id": user_id, "integration_id": integration_id},
            {"$set": doc},
            upsert=True,
        )
        _log.info(
            "Upserted integration config: user=%s integration=%s enabled=%s",
            user_id, integration_id, enabled,
        )
        return doc
