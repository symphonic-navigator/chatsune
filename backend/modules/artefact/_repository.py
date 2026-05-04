"""MongoDB repository for artefacts and artefact versions."""

import logging
from datetime import datetime, timezone

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

_log = logging.getLogger(__name__)

_MAX_VERSIONS = 20


class ArtefactRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self._artefacts = db["artefacts"]
        self._versions = db["artefact_versions"]

    async def create_indexes(self) -> None:
        await self._artefacts.create_index(
            [("session_id", 1), ("handle", 1)], unique=True,
        )
        await self._artefacts.create_index("session_id")
        await self._versions.create_index("artefact_id")

    async def create(self, doc: dict) -> dict:
        result = await self._artefacts.insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    async def get_by_handle(self, session_id: str, handle: str) -> dict | None:
        return await self._artefacts.find_one(
            {"session_id": session_id, "handle": handle},
        )

    async def get_by_id(self, artefact_id: str) -> dict | None:
        return await self._artefacts.find_one({"_id": ObjectId(artefact_id)})

    async def list_by_session(self, session_id: str) -> list[dict]:
        cursor = self._artefacts.find(
            {"session_id": session_id},
        ).sort("created_at", 1)
        return await cursor.to_list(length=200)

    async def list_by_user(self, user_id: str) -> list[dict]:
        """List all artefacts owned by ``user_id`` across all sessions, newest first."""
        cursor = self._artefacts.find(
            {"user_id": user_id},
        ).sort("updated_at", -1)
        return await cursor.to_list(length=2000)

    async def update_content(
        self,
        artefact_id: str,
        content: str,
        title: str | None,
        new_version: int,
        max_version: int,
    ) -> dict | None:
        update: dict = {
            "$set": {
                "content": content,
                "size_bytes": len(content.encode("utf-8")),
                "version": new_version,
                "max_version": max_version,
                "updated_at": datetime.now(timezone.utc),
            },
        }
        if title is not None:
            update["$set"]["title"] = title
        return await self._artefacts.find_one_and_update(
            {"_id": ObjectId(artefact_id)},
            update,
            return_document=True,
        )

    async def rename(self, artefact_id: str, title: str) -> dict | None:
        return await self._artefacts.find_one_and_update(
            {"_id": ObjectId(artefact_id)},
            {"$set": {"title": title, "updated_at": datetime.now(timezone.utc)}},
            return_document=True,
        )

    async def delete(self, artefact_id: str) -> bool:
        result = await self._artefacts.delete_one({"_id": ObjectId(artefact_id)})
        if result.deleted_count:
            await self._versions.delete_many({"artefact_id": artefact_id})
        return result.deleted_count > 0

    async def delete_by_session_ids(self, session_ids: list[str]) -> int:
        """Delete all artefacts and their versions for the given sessions."""
        if not session_ids:
            return 0
        cursor = self._artefacts.find(
            {"session_id": {"$in": session_ids}},
            projection={"_id": 1},
        )
        artefact_ids = [str(doc["_id"]) async for doc in cursor]
        if not artefact_ids:
            return 0
        await self._versions.delete_many({"artefact_id": {"$in": artefact_ids}})
        result = await self._artefacts.delete_many(
            {"_id": {"$in": [ObjectId(aid) for aid in artefact_ids]}}
        )
        return result.deleted_count

    async def list_for_sessions(self, session_ids: list[str]) -> list[dict]:
        """Return all artefact docs whose ``session_id`` is in the list."""
        if not session_ids:
            return []
        cursor = self._artefacts.find(
            {"session_id": {"$in": session_ids}},
        ).sort("created_at", 1)
        return await cursor.to_list(length=10000)

    async def count_for_sessions(self, session_ids: list[str]) -> int:
        """Mindspace: count artefacts whose ``session_id`` is in ``session_ids``.

        Empty input → 0 with no DB round-trip. Used by the project
        usage-counts endpoint and the delete-modal counts row.
        """
        if not session_ids:
            return 0
        return await self._artefacts.count_documents(
            {"session_id": {"$in": session_ids}},
        )

    async def list_versions_for_artefacts(
        self, artefact_ids: list[str],
    ) -> dict[str, list[dict]]:
        """Return ``{artefact_id: [version_doc, ...]}`` for the given ids."""
        if not artefact_ids:
            return {}
        cursor = self._versions.find(
            {"artefact_id": {"$in": artefact_ids}},
        ).sort("version", 1)
        docs = await cursor.to_list(length=100000)
        grouped: dict[str, list[dict]] = {}
        for doc in docs:
            grouped.setdefault(doc["artefact_id"], []).append(doc)
        return grouped

    async def bulk_insert_artefacts(self, docs: list[dict]) -> int:
        """Insert raw artefact docs (``_id`` already assigned as ObjectId)."""
        if not docs:
            return 0
        result = await self._artefacts.insert_many(docs)
        return len(result.inserted_ids)

    async def bulk_insert_versions(self, docs: list[dict]) -> int:
        """Insert raw version docs (``artefact_id`` already assigned)."""
        if not docs:
            return 0
        result = await self._versions.insert_many(docs)
        return len(result.inserted_ids)

    async def save_version(self, artefact_id: str, version: int, content: str, title: str) -> None:
        await self._versions.insert_one({
            "artefact_id": artefact_id,
            "version": version,
            "content": content,
            "title": title,
            "created_at": datetime.now(timezone.utc),
        })
        count = await self._versions.count_documents({"artefact_id": artefact_id})
        if count > _MAX_VERSIONS:
            oldest = await self._versions.find(
                {"artefact_id": artefact_id},
            ).sort("version", 1).limit(count - _MAX_VERSIONS).to_list(length=count)
            if oldest:
                ids = [d["_id"] for d in oldest]
                await self._versions.delete_many({"_id": {"$in": ids}})

    async def get_version(self, artefact_id: str, version: int) -> dict | None:
        return await self._versions.find_one(
            {"artefact_id": artefact_id, "version": version},
        )

    async def delete_versions_above(self, artefact_id: str, version: int) -> None:
        await self._versions.delete_many(
            {"artefact_id": artefact_id, "version": {"$gt": version}},
        )

    async def set_version_pointer(self, artefact_id: str, version: int, max_version: int) -> dict | None:
        ver_doc = await self.get_version(artefact_id, version)
        if not ver_doc:
            return None
        return await self._artefacts.find_one_and_update(
            {"_id": ObjectId(artefact_id)},
            {"$set": {
                "content": ver_doc["content"],
                "title": ver_doc.get("title", ""),
                "size_bytes": len(ver_doc["content"].encode("utf-8")),
                "version": version,
                "max_version": max_version,
                "updated_at": datetime.now(timezone.utc),
            }},
            return_document=True,
        )
