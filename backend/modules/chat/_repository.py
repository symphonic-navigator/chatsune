from datetime import UTC, datetime
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from shared.dtos.chat import ChatMessageDto, ChatSessionDto


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
        cursor = self._sessions.find({"user_id": user_id}).sort("updated_at", -1)
        return await cursor.to_list(length=200)

    async def update_session_state(self, session_id: str, state: str) -> dict | None:
        now = datetime.now(UTC)
        await self._sessions.update_one(
            {"_id": session_id}, {"$set": {"state": state, "updated_at": now}},
        )
        return await self._sessions.find_one({"_id": session_id})

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
        await self._messages.insert_one(doc)
        return doc

    async def list_messages(self, session_id: str) -> list[dict]:
        cursor = self._messages.find({"session_id": session_id}).sort("created_at", 1)
        return await cursor.to_list(length=5000)

    @staticmethod
    def session_to_dto(doc: dict) -> ChatSessionDto:
        return ChatSessionDto(
            id=doc["_id"],
            user_id=doc["user_id"],
            persona_id=doc["persona_id"],
            model_unique_id=doc["model_unique_id"],
            state=doc["state"],
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    @staticmethod
    def message_to_dto(doc: dict) -> ChatMessageDto:
        return ChatMessageDto(
            id=doc["_id"],
            session_id=doc["session_id"],
            role=doc["role"],
            content=doc["content"],
            thinking=doc.get("thinking"),
            token_count=doc["token_count"],
            created_at=doc["created_at"],
        )
