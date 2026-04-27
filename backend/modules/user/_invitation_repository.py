"""Repository for one-time admin-generated invitation tokens.

A token authorises exactly one self-registration. The unique index on
``token`` and the TTL index on ``expires_at`` are both applied at startup
via the module-level ``init_indexes`` hook.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING


class InvitationRepository:
    """CRUD for ``invitation_tokens`` collection."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["invitation_tokens"]

    async def create_indexes(self) -> None:
        # Unique index ensures token uniqueness and supports fast lookup.
        await self._collection.create_index([("token", ASCENDING)], unique=True)
        # TTL index removes documents automatically once expires_at is in the
        # past. Setting expireAfterSeconds=0 means MongoDB deletes the document
        # as soon as the field value is earlier than the current time.
        await self._collection.create_index(
            [("expires_at", ASCENDING)], expireAfterSeconds=0
        )

    async def create(self, *, created_by: str, ttl_hours: int = 24) -> dict:
        now = datetime.now(timezone.utc)
        doc = {
            "token": secrets.token_urlsafe(32),
            "created_at": now,
            "expires_at": now + timedelta(hours=ttl_hours),
            "used": False,
            "used_at": None,
            "used_by_user_id": None,
            "created_by": created_by,
        }
        result = await self._collection.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def find_by_token(self, token: str) -> dict | None:
        return await self._collection.find_one({"token": token})

    async def mark_used_atomic(
        self,
        token: str,
        *,
        used_by_user_id: str,
        session=None,
    ) -> dict | None:
        """Atomically mark the token as used.

        Filter requires ``used: false`` AND ``expires_at > now``, so this
        returns None if the token is already consumed, expired, or unknown.
        Callers translate the None return value into a 410 Gone response.
        """
        from pymongo import ReturnDocument

        now = datetime.now(timezone.utc)
        return await self._collection.find_one_and_update(
            {"token": token, "used": False, "expires_at": {"$gt": now}},
            {
                "$set": {
                    "used": True,
                    "used_at": now,
                    "used_by_user_id": used_by_user_id,
                }
            },
            return_document=ReturnDocument.AFTER,
            session=session,
        )
