import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.chat import (
    ArtefactRefDto,
    ChatMessageDto,
    ChatSessionDto,
    VisionDescriptionSnapshotDto,
    WebSearchContextItemDto,
)
from shared.dtos.storage import AttachmentRefDto


class ChatRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._sessions = db["chat_sessions"]
        self._messages = db["chat_messages"]

    async def create_indexes(self) -> None:
        await self._sessions.create_index("user_id")
        await self._sessions.create_index([("user_id", 1), ("updated_at", -1)])
        await self._messages.create_index("session_id")
        await self._messages.create_index([("session_id", 1), ("created_at", 1)])
        await self._messages.create_index(
            [("content", "text")],
            default_language="none",
            name="content_text",
        )

    async def create_session(self, user_id: str, persona_id: str, model_unique_id: str) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "persona_id": persona_id,
            "model_unique_id": model_unique_id,
            "state": "idle",
            "created_at": now,
            "updated_at": now,
        }
        await self._sessions.insert_one(doc)
        return doc

    async def get_session(self, session_id: str, user_id: str) -> dict | None:
        return await self._sessions.find_one({"_id": session_id, "user_id": user_id, "deleted_at": None})

    async def list_sessions(self, user_id: str) -> list[dict]:
        """Return sessions that have at least one message, sorted by updated_at desc."""
        pipeline = [
            {"$match": {"user_id": user_id, "deleted_at": None}},
            {"$lookup": {
                "from": "chat_messages",
                "localField": "_id",
                "foreignField": "session_id",
                "pipeline": [{"$limit": 1}],
                "as": "_msgs",
            }},
            {"$match": {"_msgs": {"$ne": []}}},
            {"$unset": "_msgs"},
            {"$sort": {"pinned": -1, "updated_at": -1}},
            {"$limit": 200},
        ]
        return await self._sessions.aggregate(pipeline).to_list(length=200)

    async def find_sessions_by_ids(self, session_ids: list[str], user_id: str) -> list[dict]:
        """Return raw session docs for the given ids that belong to the user. Soft-deleted included."""
        if not session_ids:
            return []
        cursor = self._sessions.find({"_id": {"$in": session_ids}, "user_id": user_id})
        return await cursor.to_list(length=len(session_ids))

    async def search_sessions(
        self,
        user_id: str,
        query: str,
        persona_id: str | None = None,
        exclude_persona_ids: list[str] | None = None,
    ) -> list[dict]:
        """Search sessions by message content ($text) and session title (regex).

        Returns sessions sorted by pinned desc, updated_at desc.
        Only user and assistant messages are searched (not tool messages).
        """
        # Step 1: Build session filter
        session_filter: dict = {"user_id": user_id, "deleted_at": None}
        if persona_id:
            session_filter["persona_id"] = persona_id
        if exclude_persona_ids and not persona_id:
            session_filter["persona_id"] = {"$nin": exclude_persona_ids}

        # Step 2: Get candidate session IDs for this user
        candidate_docs = await self._sessions.find(
            session_filter, {"_id": 1},
        ).to_list(length=500)
        candidate_ids = [doc["_id"] for doc in candidate_docs]
        if not candidate_ids:
            return []

        # Step 3: Text search on messages (user + assistant only)
        message_hits = await self._messages.find(
            {
                "$text": {"$search": query},
                "session_id": {"$in": candidate_ids},
                "role": {"$in": ["user", "assistant"]},
            },
            {"session_id": 1},
        ).to_list(length=5000)
        message_session_ids = {doc["session_id"] for doc in message_hits}

        # Step 4: Regex search on session titles
        terms = query.strip().split()
        title_filter = dict(session_filter)
        title_filter["_id"] = {"$in": candidate_ids}
        if terms:
            title_filter["$and"] = [
                {"title": {"$regex": re.escape(term), "$options": "i"}}
                for term in terms
            ]
        title_hits = await self._sessions.find(
            title_filter, {"_id": 1},
        ).to_list(length=500)
        title_session_ids = {doc["_id"] for doc in title_hits}

        # Step 5: Union and fetch full session docs
        matching_ids = list(message_session_ids | title_session_ids)
        if not matching_ids:
            return []

        pipeline = [
            {"$match": {"_id": {"$in": matching_ids}}},
            {"$sort": {"pinned": -1, "updated_at": -1}},
            {"$limit": 200},
        ]
        return await self._sessions.aggregate(pipeline).to_list(length=200)

    async def update_session_state(self, session_id: str, state: str) -> dict | None:
        now = datetime.now(UTC)
        await self._sessions.update_one(
            {"_id": session_id}, {"$set": {"state": state, "updated_at": now}},
        )
        return await self._sessions.find_one({"_id": session_id})

    async def update_session_title(self, session_id: str, title: str) -> dict | None:
        """Set the title of a chat session."""
        now = datetime.now(UTC)
        await self._sessions.update_one(
            {"_id": session_id},
            {"$set": {"title": title, "updated_at": now}},
        )
        return await self._sessions.find_one({"_id": session_id})

    async def update_session_pinned(self, session_id: str, pinned: bool) -> dict | None:
        """Toggle the pinned status of a chat session."""
        now = datetime.now(UTC)
        await self._sessions.update_one(
            {"_id": session_id},
            {"$set": {"pinned": pinned, "updated_at": now}},
        )
        return await self._sessions.find_one({"_id": session_id})

    async def update_session_reasoning_override(
        self, session_id: str, reasoning_override: bool | None,
    ) -> dict | None:
        now = datetime.now(UTC)
        await self._sessions.update_one(
            {"_id": session_id},
            {"$set": {"reasoning_override": reasoning_override, "updated_at": now}},
        )
        return await self._sessions.find_one({"_id": session_id})

    async def update_session_disabled_tool_groups(
        self, session_id: str, disabled_tool_groups: list[str],
    ) -> dict | None:
        now = datetime.now(UTC)
        await self._sessions.update_one(
            {"_id": session_id},
            {"$set": {"disabled_tool_groups": disabled_tool_groups, "updated_at": now}},
        )
        return await self._sessions.find_one({"_id": session_id})

    async def update_session_knowledge_library_ids(
        self, session_id: str, library_ids: list[str],
    ) -> dict | None:
        now = datetime.now(UTC)
        await self._sessions.update_one(
            {"_id": session_id},
            {"$set": {"knowledge_library_ids": library_ids, "updated_at": now}},
        )
        return await self._sessions.find_one({"_id": session_id})

    async def get_latest_active_session(
        self, user_id: str, persona_id: str,
    ) -> dict | None:
        """Return the most recently updated non-deleted session for the pair."""
        return await self._sessions.find_one(
            {"user_id": user_id, "persona_id": persona_id, "deleted_at": None},
            sort=[("updated_at", -1)],
        )

    async def find_empty_sessions(
        self, user_id: str, persona_id: str, exclude_session_id: str | None = None,
    ) -> list[str]:
        """Find session IDs with zero messages for a given user+persona."""
        session_filter: dict = {
            "user_id": user_id,
            "persona_id": persona_id,
            "deleted_at": None,
        }
        if exclude_session_id:
            session_filter["_id"] = {"$ne": exclude_session_id}
        pipeline = [
            {"$match": session_filter},
            {"$lookup": {
                "from": "chat_messages",
                "localField": "_id",
                "foreignField": "session_id",
                "pipeline": [{"$limit": 1}],
                "as": "_msgs",
            }},
            {"$match": {"_msgs": []}},
            {"$project": {"_id": 1}},
        ]
        docs = await self._sessions.aggregate(pipeline).to_list(length=100)
        return [doc["_id"] for doc in docs]

    async def delete_sessions_by_ids(self, session_ids: list[str]) -> None:
        """Hard-delete sessions by their IDs."""
        if not session_ids:
            return
        await self._sessions.delete_many({"_id": {"$in": session_ids}})

    async def delete_stale_empty_sessions(self, max_age_minutes: int = 1440) -> list[str]:
        """Delete sessions older than max_age_minutes that have zero messages. Returns list of deleted session IDs."""
        cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
        pipeline = [
            {"$match": {"created_at": {"$lt": cutoff}, "deleted_at": None}},
            {"$lookup": {
                "from": "chat_messages",
                "localField": "_id",
                "foreignField": "session_id",
                "pipeline": [{"$limit": 1}],
                "as": "_msgs",
            }},
            {"$match": {"_msgs": []}},
            {"$project": {"_id": 1}},
        ]
        stale = await self._sessions.aggregate(pipeline).to_list(length=1000)
        if not stale:
            return []
        stale_ids = [doc["_id"] for doc in stale]
        await self._sessions.delete_many({"_id": {"$in": stale_ids}})
        return stale_ids

    async def soft_delete_session(self, session_id: str, user_id: str) -> bool:
        result = await self._sessions.update_one(
            {"_id": session_id, "user_id": user_id, "deleted_at": None},
            {"$set": {"deleted_at": datetime.now(UTC)}},
        )
        return result.modified_count > 0

    async def restore_session(self, session_id: str, user_id: str) -> dict | None:
        result = await self._sessions.update_one(
            {"_id": session_id, "user_id": user_id, "deleted_at": {"$ne": None}},
            {"$set": {"deleted_at": None}},
        )
        if result.modified_count == 0:
            return None
        return await self._sessions.find_one({"_id": session_id})

    async def hard_delete_expired_sessions(self, max_age_minutes: int = 60) -> list[str]:
        """Hard-delete sessions where deleted_at is older than max_age_minutes. Returns list of deleted IDs."""
        cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
        cursor = self._sessions.find(
            {"deleted_at": {"$ne": None, "$lt": cutoff}},
            {"_id": 1},
        )
        docs = await cursor.to_list(length=1000)
        if not docs:
            return []
        ids = [doc["_id"] for doc in docs]
        await self._sessions.delete_many({"_id": {"$in": ids}})
        await self._messages.delete_many({"session_id": {"$in": ids}})
        return ids

    async def delete_by_persona(self, user_id: str, persona_id: str) -> int:
        """Hard-delete all sessions and their messages for a persona."""
        cursor = self._sessions.find(
            {"user_id": user_id, "persona_id": persona_id},
            projection={"_id": 1},
        )
        session_ids = [doc["_id"] async for doc in cursor]
        if not session_ids:
            return 0
        await self._messages.delete_many({"session_id": {"$in": session_ids}})
        result = await self._sessions.delete_many({"_id": {"$in": session_ids}})
        return result.deleted_count

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        token_count: int,
        thinking: str | None = None,
        usage: dict | None = None,
        web_search_context: list[dict] | None = None,
        knowledge_context: list[dict] | None = None,
        attachment_ids: list[str] | None = None,
        attachment_refs: list[dict] | None = None,
        vision_descriptions_used: list[dict] | None = None,
        artefact_refs: list[dict] | None = None,
        refusal_text: str | None = None,
        status: Literal["completed", "aborted", "refused"] = "completed",
    ) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "session_id": session_id,
            "role": role,
            "content": content,
            "thinking": thinking,
            "token_count": token_count,
            "created_at": now,
            "status": status,
        }
        if web_search_context:
            doc["web_search_context"] = web_search_context
        if knowledge_context:
            doc["knowledge_context"] = knowledge_context
        if attachment_ids:
            doc["attachment_ids"] = attachment_ids
        if attachment_refs:
            doc["attachment_refs"] = attachment_refs
        if vision_descriptions_used:
            doc["vision_descriptions_used"] = vision_descriptions_used
        if usage:
            doc["usage"] = usage
        if artefact_refs:
            doc["artefact_refs"] = artefact_refs
        if refusal_text:
            doc["refusal_text"] = refusal_text
        await self._messages.insert_one(doc)
        return doc

    async def update_message_vision_snapshots(
        self, message_id: str, snapshots: list[dict],
    ) -> None:
        """Persist vision-description snapshots on an existing message."""
        await self._messages.update_one(
            {"_id": message_id},
            {"$set": {"vision_descriptions_used": snapshots}},
        )

    async def count_messages(self, session_id: str) -> int:
        """Return the number of messages in a session."""
        return await self._messages.count_documents({"session_id": session_id})

    async def list_messages(self, session_id: str) -> list[dict]:
        cursor = self._messages.find({"session_id": session_id}).sort("created_at", 1)
        return await cursor.to_list(length=5000)

    async def list_unextracted_user_messages(
        self, session_id: str, limit: int = 20,
    ) -> list[dict]:
        """Return user messages not yet processed for memory extraction, oldest first."""
        cursor = (
            self._messages.find({
                "session_id": session_id,
                "role": "user",
                "extracted_at": {"$exists": False},
            })
            .sort("created_at", 1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    async def mark_messages_extracted(
        self, message_ids: list[str], *, session=None,
    ) -> int:
        """Set extracted_at on the given messages. Returns count of updated docs."""
        if not message_ids:
            return 0
        result = await self._messages.update_many(
            {"_id": {"$in": message_ids}},
            {"$set": {"extracted_at": datetime.now(UTC)}},
            session=session,
        )
        return result.modified_count

    async def delete_messages_after(self, session_id: str, message_id: str) -> bool:
        """Delete all messages in a session created after the given message."""
        target = await self._messages.find_one({"_id": message_id, "session_id": session_id})
        if target is None:
            return False
        await self._messages.delete_many({
            "session_id": session_id,
            "_id": {"$ne": message_id},
            "created_at": {"$gte": target["created_at"]},
        })
        return True

    async def update_message_content(
        self, message_id: str, content: str, token_count: int,
    ) -> dict | None:
        """Overwrite a message's content and token count."""
        await self._messages.update_one(
            {"_id": message_id},
            {"$set": {"content": content, "token_count": token_count}},
        )
        return await self._messages.find_one({"_id": message_id})

    async def get_last_message(self, session_id: str) -> dict | None:
        """Return the last message in a session by created_at, or None."""
        cursor = self._messages.find({"session_id": session_id}).sort("created_at", -1).limit(1)
        docs = await cursor.to_list(length=1)
        return docs[0] if docs else None

    async def delete_message(self, message_id: str) -> bool:
        """Delete a single message by ID."""
        result = await self._messages.delete_one({"_id": message_id})
        return result.deleted_count > 0

    async def edit_message_atomic(
        self, session_id: str, message_id: str, new_content: str, token_count: int,
    ) -> bool:
        """Delete messages after target and update target content atomically in a transaction."""
        from backend.database import get_client
        client = get_client()
        async with await client.start_session() as session:
            async with session.start_transaction():
                target = await self._messages.find_one(
                    {"_id": message_id, "session_id": session_id}, session=session,
                )
                if target is None:
                    return False
                await self._messages.delete_many(
                    {
                        "session_id": session_id,
                        "_id": {"$ne": message_id},
                        "created_at": {"$gte": target["created_at"]},
                    },
                    session=session,
                )
                await self._messages.update_one(
                    {"_id": message_id},
                    {"$set": {
                        "content": new_content,
                        "token_count": token_count,
                        "updated_at": datetime.now(UTC),
                    }},
                    session=session,
                )
        return True

    @staticmethod
    def session_to_dto(doc: dict) -> ChatSessionDto:
        return ChatSessionDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            persona_id=doc["persona_id"],
            model_unique_id=doc["model_unique_id"],
            state=doc["state"],
            title=doc.get("title"),
            disabled_tool_groups=doc.get("disabled_tool_groups", []),
            reasoning_override=doc.get("reasoning_override"),
            pinned=doc.get("pinned", False),
            context_status=doc.get("context_status", "green"),
            context_fill_percentage=float(doc.get("context_fill_percentage", 0.0)),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    async def update_session_context_metrics(
        self, session_id: str, status: str, fill_percentage: float,
    ) -> None:
        """Persist the last-known context window utilisation on the session.

        Called at stream-end so that reopening the chat later can hydrate the
        context pill without waiting for the next inference to complete.
        """
        await self._sessions.update_one(
            {"_id": session_id},
            {"$set": {
                "context_status": status,
                "context_fill_percentage": float(fill_percentage),
            }},
        )

    @staticmethod
    def message_to_dto(doc: dict) -> ChatMessageDto:
        raw_ctx = doc.get("web_search_context")
        ws_ctx = (
            [
                WebSearchContextItemDto(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("snippet", ""),
                    source_type=item.get("source_type", "search"),
                )
                for item in raw_ctx
            ]
            if raw_ctx
            else None
        )
        raw_refs = doc.get("attachment_refs")
        attachments = (
            [
                AttachmentRefDto(
                    file_id=ref.get("file_id", ""),
                    display_name=ref.get("display_name", ""),
                    media_type=ref.get("media_type", ""),
                    size_bytes=ref.get("size_bytes", 0),
                    thumbnail_b64=ref.get("thumbnail_b64"),
                    text_preview=ref.get("text_preview"),
                )
                for ref in raw_refs
            ]
            if raw_refs
            else None
        )
        raw_vision_snaps = doc.get("vision_descriptions_used")
        vision_snaps = (
            [
                VisionDescriptionSnapshotDto(
                    file_id=s.get("file_id", ""),
                    display_name=s.get("display_name", ""),
                    model_id=s.get("model_id", ""),
                    text=s.get("text", ""),
                )
                for s in raw_vision_snaps
            ]
            if raw_vision_snaps
            else None
        )
        raw_artefact_refs = doc.get("artefact_refs")
        artefact_refs = (
            [
                ArtefactRefDto(
                    artefact_id=ref.get("artefact_id", ""),
                    handle=ref.get("handle", ""),
                    title=ref.get("title", ""),
                    artefact_type=ref.get("artefact_type", ""),
                    operation=ref.get("operation", "create"),
                )
                for ref in raw_artefact_refs
            ]
            if raw_artefact_refs
            else None
        )
        return ChatMessageDto(
            id=doc["_id"],
            session_id=doc["session_id"],
            role=doc["role"],
            content=doc["content"],
            thinking=doc.get("thinking"),
            token_count=doc["token_count"],
            attachments=attachments,
            web_search_context=ws_ctx,
            knowledge_context=doc.get("knowledge_context"),
            vision_descriptions_used=vision_snaps,
            created_at=doc["created_at"],
            status=doc.get("status", "completed"),
            refusal_text=doc.get("refusal_text"),
            artefact_refs=artefact_refs,
            usage=doc.get("usage"),
        )
