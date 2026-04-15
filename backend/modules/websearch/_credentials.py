"""Web-search credentials — one API key per user per provider."""

from datetime import UTC, datetime
from uuid import uuid4

from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.config import settings
from shared.dtos.websearch import WebSearchCredentialDto


def _fernet() -> Fernet:
    return Fernet(settings.encryption_key.encode())


class WebSearchCredentialRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["websearch_user_credentials"]

    async def create_indexes(self) -> None:
        await self._collection.create_index(
            [("user_id", 1), ("provider_id", 1)], unique=True
        )

    async def find(self, user_id: str, provider_id: str) -> dict | None:
        return await self._collection.find_one(
            {"user_id": user_id, "provider_id": provider_id}
        )

    async def upsert(
        self, user_id: str, provider_id: str, api_key: str
    ) -> dict:
        now = datetime.now(UTC)
        encrypted = _fernet().encrypt(api_key.encode()).decode()
        return await self._collection.find_one_and_update(
            {"user_id": user_id, "provider_id": provider_id},
            {
                "$set": {
                    "api_key_encrypted": encrypted,
                    "last_test_status": None,
                    "last_test_error": None,
                    "last_test_at": None,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "_id": str(uuid4()),
                    "user_id": user_id,
                    "provider_id": provider_id,
                    "created_at": now,
                },
            },
            upsert=True,
            return_document=True,
        )

    async def delete(self, user_id: str, provider_id: str) -> bool:
        res = await self._collection.delete_one(
            {"user_id": user_id, "provider_id": provider_id}
        )
        return res.deleted_count > 0

    async def delete_all_for_user(self, user_id: str) -> int:
        """Delete every stored web-search credential owned by ``user_id``.

        Used by the user self-delete cascade (right-to-be-forgotten).
        """
        res = await self._collection.delete_many({"user_id": user_id})
        return res.deleted_count

    async def update_test(
        self,
        user_id: str,
        provider_id: str,
        *,
        status: str,
        error: str | None,
    ) -> dict | None:
        now = datetime.now(UTC)
        return await self._collection.find_one_and_update(
            {"user_id": user_id, "provider_id": provider_id},
            {
                "$set": {
                    "last_test_status": status,
                    "last_test_error": error,
                    "last_test_at": now,
                    "updated_at": now,
                },
            },
            return_document=True,
        )

    async def get_key(self, user_id: str, provider_id: str) -> str | None:
        """Return the decrypted API key for the given user + provider, or None."""
        doc = await self._collection.find_one(
            {"user_id": user_id, "provider_id": provider_id}
        )
        if doc is None:
            return None
        encrypted = doc.get("api_key_encrypted")
        if encrypted is None:
            return None
        return _fernet().decrypt(encrypted.encode()).decode()

    def get_raw_key(self, doc: dict) -> str:
        return _fernet().decrypt(doc["api_key_encrypted"].encode()).decode()

    @staticmethod
    def to_dto(
        doc: dict | None, provider_id: str
    ) -> WebSearchCredentialDto:
        if doc is None:
            return WebSearchCredentialDto(
                provider_id=provider_id,
                is_configured=False,
            )
        return WebSearchCredentialDto(
            provider_id=provider_id,
            is_configured=True,
            last_test_status=doc.get("last_test_status"),
            last_test_error=doc.get("last_test_error"),
            last_test_at=doc.get("last_test_at"),
        )
