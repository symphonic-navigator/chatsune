"""MongoDB repository for the memory module."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

_MAX_MEMORY_BODY_VERSIONS = 5


class MemoryRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._entries = db["memory_journal_entries"]
        self._bodies = db["memory_bodies"]

    async def create_indexes(self) -> None:
        await self._entries.create_index([("user_id", 1), ("persona_id", 1), ("state", 1)])
        await self._entries.create_index([("user_id", 1), ("persona_id", 1), ("created_at", -1)])
        await self._entries.create_index([("state", 1), ("created_at", 1)])
        await self._bodies.create_index([("user_id", 1), ("persona_id", 1), ("version", -1)])

    # -------------------------------------------------------------------------
    # Journal entries
    # -------------------------------------------------------------------------

    async def create_journal_entry(
        self,
        *,
        user_id: str,
        persona_id: str,
        content: str,
        category: str | None,
        source_session_id: str,
        is_correction: bool = False,
    ) -> str:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "persona_id": persona_id,
            "content": content,
            "category": category,
            "source_session_id": source_session_id,
            "state": "uncommitted",
            "is_correction": is_correction,
            "archived_by_dream_id": None,
            "created_at": now,
            "committed_at": None,
            "auto_committed": False,
        }
        await self._entries.insert_one(doc)
        return doc["_id"]

    async def list_journal_entries(
        self,
        user_id: str,
        persona_id: str,
        *,
        state: str | None = None,
    ) -> list[dict]:
        query: dict = {"user_id": user_id, "persona_id": persona_id}
        if state is not None:
            query["state"] = state
        cursor = self._entries.find(query).sort("created_at", -1)
        docs = await cursor.to_list(length=5000)
        return [_entry_to_dict(doc) for doc in docs]

    async def count_entries(self, user_id: str, persona_id: str, *, state: str) -> int:
        return await self._entries.count_documents(
            {"user_id": user_id, "persona_id": persona_id, "state": state},
        )

    async def commit_entry(self, entry_id: str, user_id: str) -> bool:
        now = datetime.now(UTC)
        result = await self._entries.update_one(
            {"_id": entry_id, "user_id": user_id},
            {"$set": {"state": "committed", "committed_at": now, "auto_committed": False}},
        )
        return result.modified_count > 0

    async def update_entry(self, entry_id: str, user_id: str, *, content: str) -> bool:
        result = await self._entries.update_one(
            {"_id": entry_id, "user_id": user_id},
            {"$set": {"content": content}},
        )
        return result.modified_count > 0

    async def delete_entry(self, entry_id: str, user_id: str) -> bool:
        result = await self._entries.delete_one({"_id": entry_id, "user_id": user_id})
        return result.deleted_count > 0

    async def auto_commit_old_entries(self, *, max_age_hours: int = 48) -> list[dict]:
        """Find uncommitted entries older than cutoff and commit them automatically."""
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        now = datetime.now(UTC)
        cursor = self._entries.find(
            {"state": "uncommitted", "created_at": {"$lt": cutoff}},
        )
        docs = await cursor.to_list(length=5000)
        if not docs:
            return []
        ids = [doc["_id"] for doc in docs]
        await self._entries.update_many(
            {"_id": {"$in": ids}},
            {"$set": {"state": "committed", "committed_at": now, "auto_committed": True}},
        )
        updated_cursor = self._entries.find({"_id": {"$in": ids}})
        updated_docs = await updated_cursor.to_list(length=5000)
        return [_entry_to_dict(doc) for doc in updated_docs]

    async def discard_oldest_uncommitted(
        self, user_id: str, persona_id: str, *, max_count: int = 50,
    ) -> int:
        """Delete the oldest uncommitted entries exceeding max_count. Returns number deleted."""
        total = await self._entries.count_documents(
            {"user_id": user_id, "persona_id": persona_id, "state": "uncommitted"},
        )
        excess = total - max_count
        if excess <= 0:
            return 0
        cursor = (
            self._entries
            .find(
                {"user_id": user_id, "persona_id": persona_id, "state": "uncommitted"},
                {"_id": 1},
            )
            .sort("created_at", 1)
            .limit(excess)
        )
        to_delete = await cursor.to_list(length=excess)
        if not to_delete:
            return 0
        ids = [doc["_id"] for doc in to_delete]
        result = await self._entries.delete_many({"_id": {"$in": ids}})
        return result.deleted_count

    async def archive_entries(self, user_id: str, persona_id: str, *, dream_id: str) -> int:
        """Archive all committed entries for a persona under a dream run. Returns count archived."""
        result = await self._entries.update_many(
            {"user_id": user_id, "persona_id": persona_id, "state": "committed"},
            {"$set": {"state": "archived", "archived_by_dream_id": dream_id}},
        )
        return result.modified_count

    # -------------------------------------------------------------------------
    # Memory bodies
    # -------------------------------------------------------------------------

    async def save_memory_body(
        self,
        *,
        user_id: str,
        persona_id: str,
        content: str,
        token_count: int,
        entries_processed: int,
    ) -> int:
        """Save a new memory body version, prune old versions beyond the max. Returns new version number."""
        # Determine next version number.
        latest = await self._bodies.find_one(
            {"user_id": user_id, "persona_id": persona_id},
            sort=[("version", -1)],
        )
        new_version = (latest["version"] + 1) if latest else 1

        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "persona_id": persona_id,
            "content": content,
            "token_count": token_count,
            "version": new_version,
            "entries_processed": entries_processed,
            "created_at": datetime.now(UTC),
        }
        await self._bodies.insert_one(doc)

        # Prune versions beyond the maximum retained.
        all_versions = await (
            self._bodies
            .find({"user_id": user_id, "persona_id": persona_id}, {"_id": 1, "version": 1})
            .sort("version", -1)
            .to_list(length=1000)
        )
        if len(all_versions) > _MAX_MEMORY_BODY_VERSIONS:
            excess_ids = [v["_id"] for v in all_versions[_MAX_MEMORY_BODY_VERSIONS:]]
            await self._bodies.delete_many({"_id": {"$in": excess_ids}})

        return new_version

    async def get_current_memory_body(self, user_id: str, persona_id: str) -> dict | None:
        doc = await self._bodies.find_one(
            {"user_id": user_id, "persona_id": persona_id},
            sort=[("version", -1)],
        )
        return _body_to_dict(doc) if doc else None

    async def get_memory_body_version(
        self, user_id: str, persona_id: str, *, version: int,
    ) -> dict | None:
        doc = await self._bodies.find_one(
            {"user_id": user_id, "persona_id": persona_id, "version": version},
        )
        return _body_to_dict(doc) if doc else None

    async def list_memory_body_versions(self, user_id: str, persona_id: str) -> list[dict]:
        """Return all versions without the content field, newest first."""
        cursor = (
            self._bodies
            .find(
                {"user_id": user_id, "persona_id": persona_id},
                {"content": 0},
            )
            .sort("version", -1)
        )
        docs = await cursor.to_list(length=1000)
        return [_body_to_dict(doc) for doc in docs]

    async def rollback_memory_body(
        self, user_id: str, persona_id: str, *, to_version: int,
    ) -> int:
        """Copy a previous version's content into a new version. Returns the new version number."""
        source = await self._bodies.find_one(
            {"user_id": user_id, "persona_id": persona_id, "version": to_version},
        )
        if source is None:
            msg = f"Memory body version {to_version} not found for persona {persona_id}"
            raise ValueError(msg)

        return await self.save_memory_body(
            user_id=user_id,
            persona_id=persona_id,
            content=source["content"],
            token_count=source["token_count"],
            entries_processed=source["entries_processed"],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry_to_dict(doc: dict) -> dict:
    result = dict(doc)
    result["id"] = result.pop("_id")
    return result


def _body_to_dict(doc: dict) -> dict:
    result = dict(doc)
    result["id"] = result.pop("_id")
    return result
