"""MongoDB access for ChatGPT-import collections.

Two collections:
- ``chatgpt_imports`` — parent upload record (per user, one active at a time).
- ``chatgpt_import_conversations`` — child documents, one per parsed conversation.

Both carry an ``expires_at`` field with a TTL index so the records evaporate
14 days after the last import action.
"""
from datetime import UTC, datetime, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase


class ChatGptImportRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._imports = db["chatgpt_imports"]
        self._conversations = db["chatgpt_import_conversations"]

    async def create_indexes(self) -> None:
        await self._imports.create_index([("user_id", 1)])
        await self._imports.create_index(
            [("expires_at", 1)], expireAfterSeconds=0
        )
        await self._imports.create_index(
            [("user_id", 1), ("file_hash", 1)],
            unique=False,
        )
        await self._conversations.create_index(
            [("user_id", 1), ("import_id", 1), ("create_time", -1)]
        )
        await self._conversations.create_index(
            [("user_id", 1), ("chatgpt_conversation_id", 1)]
        )
        await self._conversations.create_index(
            [("expires_at", 1)], expireAfterSeconds=0
        )

    # --- imports collection ---------------------------------------------

    async def create_import(
        self,
        *,
        user_id: str,
        file_hash: str,
        file_size_bytes: int,
        filename: str,
        ttl_days: int = 14,
    ) -> str:
        now = datetime.now(UTC)
        doc = {
            "user_id": user_id,
            "file_hash": file_hash,
            "file_size_bytes": file_size_bytes,
            "uploaded_filename": filename,
            "status": "parsing",
            "error_message": None,
            "conversation_count": 0,
            "skipped_count": 0,
            "skipped_reasons": {},
            "created_at": now,
            "expires_at": now + timedelta(days=ttl_days),
            "last_import_at": None,
        }
        result = await self._imports.insert_one(doc)
        return str(result.inserted_id)

    async def get_import(self, import_id: str) -> dict | None:
        from bson import ObjectId
        try:
            oid = ObjectId(import_id)
        except Exception:
            return None
        return await self._imports.find_one({"_id": oid})

    async def get_active_import(self, user_id: str) -> dict | None:
        return await self._imports.find_one({"user_id": user_id})

    async def find_import_by_hash(
        self, user_id: str, file_hash: str
    ) -> dict | None:
        return await self._imports.find_one(
            {"user_id": user_id, "file_hash": file_hash}
        )

    async def update_import_status(
        self,
        import_id: str,
        *,
        status: str,
        conversation_count: int | None = None,
        skipped_count: int | None = None,
        skipped_reasons: dict[str, int] | None = None,
        error_message: str | None = None,
    ) -> None:
        from bson import ObjectId
        update: dict = {"status": status}
        if conversation_count is not None:
            update["conversation_count"] = conversation_count
        if skipped_count is not None:
            update["skipped_count"] = skipped_count
        if skipped_reasons is not None:
            update["skipped_reasons"] = skipped_reasons
        if error_message is not None:
            update["error_message"] = error_message
        await self._imports.update_one(
            {"_id": ObjectId(import_id)}, {"$set": update}
        )

    async def reset_ttl(
        self, import_id: str, *, ttl_days: int = 14
    ) -> None:
        from bson import ObjectId
        now = datetime.now(UTC)
        oid = ObjectId(import_id)
        await self._imports.update_one(
            {"_id": oid},
            {
                "$set": {
                    "expires_at": now + timedelta(days=ttl_days),
                    "last_import_at": now,
                }
            },
        )
        await self._conversations.update_many(
            {"import_id": oid},
            {"$set": {"expires_at": now + timedelta(days=ttl_days)}},
        )

    async def delete_import(self, import_id: str) -> None:
        from bson import ObjectId
        oid = ObjectId(import_id)
        await self._conversations.delete_many({"import_id": oid})
        await self._imports.delete_one({"_id": oid})

    # --- conversations collection --------------------------------------

    async def insert_conversation(
        self,
        *,
        import_id: str,
        user_id: str,
        chatgpt_conversation_id: str,
        title: str,
        create_time: datetime,
        update_time: datetime,
        default_model_slug: str | None,
        message_count: int,
        first_user_message_preview: str,
        first_assistant_message_preview: str,
        raw_data: dict,
    ) -> None:
        from bson import ObjectId
        oid = ObjectId(import_id)
        parent = await self._imports.find_one({"_id": oid})
        expires_at = (
            parent["expires_at"] if parent else datetime.now(UTC) + timedelta(days=14)
        )
        doc = {
            "import_id": oid,
            "user_id": user_id,
            "chatgpt_conversation_id": chatgpt_conversation_id,
            "title": title,
            "create_time": create_time,
            "update_time": update_time,
            "default_model_slug": default_model_slug,
            "message_count": message_count,
            "first_user_message_preview": first_user_message_preview,
            "first_assistant_message_preview": first_assistant_message_preview,
            "raw_data": raw_data,
            "imports": [],
            "expires_at": expires_at,
        }
        await self._conversations.insert_one(doc)

    async def list_conversations(
        self,
        *,
        user_id: str,
        import_id: str,
        title_search: str | None = None,
        sort: str = "create_time_desc",
    ) -> list[dict]:
        from bson import ObjectId
        query: dict = {"user_id": user_id, "import_id": ObjectId(import_id)}
        if title_search:
            # Defensive: escape regex special chars so a user query of
            # ``foo.bar`` does not accidentally turn into a pattern match.
            import re as _re
            query["title"] = {"$regex": _re.escape(title_search), "$options": "i"}
        sort_fields = {
            "create_time_desc": [("create_time", -1)],
            "create_time_asc": [("create_time", 1)],
            "title_asc": [("title", 1)],
        }.get(sort, [("create_time", -1)])
        cursor = self._conversations.find(query).sort(sort_fields)
        return await cursor.to_list(length=None)

    async def get_conversation(
        self, *, user_id: str, import_id: str, chatgpt_conversation_id: str
    ) -> dict | None:
        from bson import ObjectId
        return await self._conversations.find_one(
            {
                "user_id": user_id,
                "import_id": ObjectId(import_id),
                "chatgpt_conversation_id": chatgpt_conversation_id,
            }
        )

    async def record_import(
        self,
        *,
        import_id: str,
        chatgpt_conversation_id: str,
        persona_id: str,
        session_id: str,
    ) -> None:
        from bson import ObjectId
        await self._conversations.update_one(
            {
                "import_id": ObjectId(import_id),
                "chatgpt_conversation_id": chatgpt_conversation_id,
            },
            {
                "$push": {
                    "imports": {
                        "persona_id": persona_id,
                        "session_id": session_id,
                        "imported_at": datetime.now(UTC),
                    }
                }
            },
        )

    async def list_imported_session_ids_chronological(
        self,
        *,
        import_id: str,
        persona_id: str,
    ) -> list[str]:
        """Return all session_ids imported under ``(import_id, persona_id)``.

        Ordered by the original ChatGPT ``create_time`` ascending. Used by
        the memory-batch trigger so the batch handler processes the
        oldest conversation first — the spec's anti-contradiction
        invariant: later conversations may correct earlier facts; reversed
        order would mark corrections as duplicates of their originals.
        """
        from bson import ObjectId
        cursor = self._conversations.find(
            {
                "import_id": ObjectId(import_id),
                "imports.persona_id": persona_id,
            },
            projection={"create_time": 1, "imports": 1},
        ).sort("create_time", 1)
        out: list[str] = []
        async for doc in cursor:
            for imp in doc.get("imports") or []:
                if imp.get("persona_id") == persona_id and imp.get("session_id"):
                    out.append(imp["session_id"])
                    break
        return out
