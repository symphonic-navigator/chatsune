"""Repositories for the images module."""

from datetime import datetime, UTC
from typing import Iterable

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from backend.modules.images._models import GeneratedImageDocument, UserImageConfigDocument


class GeneratedImagesRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["generated_images"]

    async def create_indexes(self) -> None:
        await self._collection.create_index([("user_id", 1), ("generated_at", -1)])
        await self._collection.create_index([("user_id", 1), ("id", 1)], unique=True)

    async def insert(self, doc: GeneratedImageDocument) -> None:
        payload = doc.model_dump()
        # Use the document's id as the Mongo _id to make ownership-checked
        # finds simple and idempotent. Composite (user_id, id) unique index
        # provides the actual safety net.
        payload["_id"] = doc.id
        await self._collection.insert_one(payload)

    async def insert_many(self, docs: Iterable[GeneratedImageDocument]) -> None:
        payloads = []
        for d in docs:
            p = d.model_dump()
            p["_id"] = d.id
            payloads.append(p)
        if payloads:
            await self._collection.insert_many(payloads)

    async def find_for_user(
        self, *, user_id: str, image_id: str
    ) -> GeneratedImageDocument | None:
        raw = await self._collection.find_one({"user_id": user_id, "id": image_id})
        if raw is None:
            return None
        raw.pop("_id", None)
        return GeneratedImageDocument.model_validate(raw)

    async def find_many_for_user(
        self, *, user_id: str, image_ids: list[str]
    ) -> list[GeneratedImageDocument]:
        """Bulk variant of ``find_for_user`` for back-fill enrichment paths.

        Returns the documents that exist and belong to the user; missing
        ids are silently dropped. The result is unordered — callers that
        need a lookup map should re-key by ``doc.id`` themselves.
        """
        if not image_ids:
            return []
        cursor = self._collection.find({
            "user_id": user_id,
            "id": {"$in": image_ids},
        })
        out: list[GeneratedImageDocument] = []
        async for raw in cursor:
            raw.pop("_id", None)
            out.append(GeneratedImageDocument.model_validate(raw))
        return out

    async def list_for_user(
        self,
        *,
        user_id: str,
        limit: int,
        before: datetime | None,
    ) -> list[GeneratedImageDocument]:
        query: dict = {"user_id": user_id}
        if before is not None:
            query["generated_at"] = {"$lt": before}
        cursor = self._collection.find(query).sort("generated_at", -1).limit(limit)
        rows = await cursor.to_list(length=limit)
        out: list[GeneratedImageDocument] = []
        for r in rows:
            r.pop("_id", None)
            out.append(GeneratedImageDocument.model_validate(r))
        return out

    async def delete_for_user(self, *, user_id: str, image_id: str) -> bool:
        result = await self._collection.delete_one(
            {"user_id": user_id, "id": image_id}
        )
        return result.deleted_count > 0

    async def delete_all_for_user(self, *, user_id: str) -> int:
        """Delete every generated image owned by ``user_id``.

        Used by the user self-delete cascade (right-to-be-forgotten).
        """
        result = await self._collection.delete_many({"user_id": user_id})
        return result.deleted_count


class UserImageConfigRepository:
    """Repository for the ``user_image_configs`` collection.

    Document ``_id`` is the composite key ``{user_id}:{connection_id}:{group_id}``.
    At most one document per user may carry ``selected=True``; the ``set_active``
    method switches that flag atomically inside a MongoDB transaction.
    """

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["user_image_configs"]
        # Motor exposes the underlying client via AsyncIOMotorDatabase.client,
        # which is what we need to open a session for transactions.
        self._client: AsyncIOMotorClient = db.client

    async def create_indexes(self) -> None:
        # Fast look-up of all configs for a user (listing, cascade delete).
        await self._collection.create_index([("user_id", 1)])
        # Partial index over (user_id, selected) for the "at most one selected
        # per user" invariant and for efficient get_active queries.
        await self._collection.create_index(
            [("user_id", 1), ("selected", 1)],
            partialFilterExpression={"selected": True},
        )

    @staticmethod
    def _doc_id(user_id: str, connection_id: str, group_id: str) -> str:
        return f"{user_id}:{connection_id}:{group_id}"

    async def upsert(
        self,
        *,
        user_id: str,
        connection_id: str,
        group_id: str,
        config: dict,
    ) -> UserImageConfigDocument:
        """Create or update a config document.

        New documents are created with ``selected=False``; the caller must call
        ``set_active`` explicitly if the new config should become active.
        The ``selected`` flag is preserved unchanged on updates.
        """
        doc_id = self._doc_id(user_id, connection_id, group_id)
        now = datetime.now(UTC)
        result = await self._collection.find_one_and_update(
            {"_id": doc_id},
            {
                "$set": {
                    "id": doc_id,
                    "user_id": user_id,
                    "connection_id": connection_id,
                    "group_id": group_id,
                    "config": config,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "selected": False,
                },
            },
            upsert=True,
            return_document=True,
        )
        result.pop("_id", None)
        return UserImageConfigDocument.model_validate(result)

    async def set_active(
        self,
        *,
        user_id: str,
        connection_id: str,
        group_id: str,
    ) -> None:
        """Atomically move the ``selected=True`` flag to the specified config.

        All other configs for ``user_id`` are set to ``selected=False`` in the
        same transaction, ensuring the invariant that at most one config per
        user is selected at any time.
        """
        doc_id = self._doc_id(user_id, connection_id, group_id)
        async with await self._client.start_session() as session:
            async with session.start_transaction():
                await self._collection.update_many(
                    {"user_id": user_id, "selected": True},
                    {"$set": {"selected": False}},
                    session=session,
                )
                await self._collection.update_one(
                    {"_id": doc_id},
                    {"$set": {"selected": True}},
                    session=session,
                )

    async def get_active(self, *, user_id: str) -> UserImageConfigDocument | None:
        """Return the currently selected config for ``user_id``, or ``None``."""
        raw = await self._collection.find_one({"user_id": user_id, "selected": True})
        if raw is None:
            return None
        raw.pop("_id", None)
        return UserImageConfigDocument.model_validate(raw)

    async def find(
        self,
        *,
        user_id: str,
        connection_id: str,
        group_id: str,
    ) -> UserImageConfigDocument | None:
        """Return a specific config by composite key, or ``None``."""
        doc_id = self._doc_id(user_id, connection_id, group_id)
        raw = await self._collection.find_one({"_id": doc_id})
        if raw is None:
            return None
        raw.pop("_id", None)
        return UserImageConfigDocument.model_validate(raw)

    async def list_for_user(self, *, user_id: str) -> list[UserImageConfigDocument]:
        """Return all configs for ``user_id``."""
        cursor = self._collection.find({"user_id": user_id})
        rows = await cursor.to_list(length=None)
        out: list[UserImageConfigDocument] = []
        for r in rows:
            r.pop("_id", None)
            out.append(UserImageConfigDocument.model_validate(r))
        return out

    async def delete_all_for_user(self, *, user_id: str) -> int:
        """Delete every config owned by ``user_id``.

        Used by the user self-delete cascade (right-to-be-forgotten).
        Returns the number of documents deleted.
        """
        result = await self._collection.delete_many({"user_id": user_id})
        return result.deleted_count
