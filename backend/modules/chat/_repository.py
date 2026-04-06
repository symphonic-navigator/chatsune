from datetime import UTC, datetime, timedelta
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.chat import ChatMessageDto, ChatSessionDto, WebSearchContextItemDto
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
        return await self._sessions.find_one({"_id": session_id, "user_id": user_id})

    async def list_sessions(self, user_id: str) -> list[dict]:
        """Return sessions that have at least one message, sorted by updated_at desc."""
        pipeline = [
            {"$match": {"user_id": user_id}},
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

    async def delete_stale_empty_sessions(self, max_age_minutes: int = 1440) -> list[str]:
        """Delete sessions older than max_age_minutes that have zero messages. Returns list of deleted session IDs."""
        cutoff = datetime.now(UTC) - timedelta(minutes=max_age_minutes)
        pipeline = [
            {"$match": {"created_at": {"$lt": cutoff}}},
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

    async def delete_session(self, session_id: str, user_id: str) -> bool:
        result = await self._sessions.delete_one({"_id": session_id, "user_id": user_id})
        if result.deleted_count > 0:
            await self._messages.delete_many({"session_id": session_id})
            return True
        return False

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        token_count: int,
        thinking: str | None = None,
        web_search_context: list[dict] | None = None,
        attachment_ids: list[str] | None = None,
        attachment_refs: list[dict] | None = None,
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
        }
        if web_search_context:
            doc["web_search_context"] = web_search_context
        if attachment_ids:
            doc["attachment_ids"] = attachment_ids
        if attachment_refs:
            doc["attachment_refs"] = attachment_refs
        await self._messages.insert_one(doc)
        return doc

    async def count_messages(self, session_id: str) -> int:
        """Return the number of messages in a session."""
        return await self._messages.count_documents({"session_id": session_id})

    async def list_messages(self, session_id: str) -> list[dict]:
        cursor = self._messages.find({"session_id": session_id}).sort("created_at", 1)
        return await cursor.to_list(length=5000)

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
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
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
        return ChatMessageDto(
            id=doc["_id"],
            session_id=doc["session_id"],
            role=doc["role"],
            content=doc["content"],
            thinking=doc.get("thinking"),
            token_count=doc["token_count"],
            attachments=attachments,
            web_search_context=ws_ctx,
            created_at=doc["created_at"],
        )
