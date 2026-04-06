from datetime import UTC, datetime
from uuid import uuid4

from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.config import settings
from shared.dtos.llm import ProviderCredentialDto


def _fernet() -> Fernet:
    return Fernet(settings.encryption_key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


class CredentialRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["llm_user_credentials"]

    async def create_indexes(self) -> None:
        await self._collection.create_index(
            [("user_id", 1), ("provider_id", 1)], unique=True
        )

    async def find(self, user_id: str, provider_id: str) -> dict | None:
        return await self._collection.find_one(
            {"user_id": user_id, "provider_id": provider_id}
        )

    async def upsert(self, user_id: str, provider_id: str, api_key: str) -> dict:
        now = datetime.now(UTC)
        encrypted = encrypt(api_key)
        result = await self._collection.find_one_and_update(
            {"user_id": user_id, "provider_id": provider_id},
            {
                "$set": {
                    "api_key_encrypted": encrypted,
                    "test_status": "untested",
                    "last_test_error": None,
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
        return result

    async def update_test_status(
        self, user_id: str, provider_id: str, test_status: str, last_test_error: str | None = None
    ) -> dict | None:
        now = datetime.now(UTC)
        result = await self._collection.find_one_and_update(
            {"user_id": user_id, "provider_id": provider_id},
            {"$set": {
                "test_status": test_status,
                "last_test_error": last_test_error,
                "updated_at": now,
            }},
            return_document=True,
        )
        return result

    async def delete(self, user_id: str, provider_id: str) -> bool:
        result = await self._collection.delete_one(
            {"user_id": user_id, "provider_id": provider_id}
        )
        return result.deleted_count > 0

    async def list_for_user(self, user_id: str) -> list[dict]:
        cursor = self._collection.find({"user_id": user_id})
        return await cursor.to_list(length=100)

    async def list_all(self) -> list[dict]:
        """List all credentials across all users. Admin use only."""
        cursor = self._collection.find({}, {"user_id": 1, "provider_id": 1, "_id": 0})
        return await cursor.to_list(length=10000)

    def get_raw_key(self, doc: dict) -> str:
        """Decrypt and return the raw API key. Use only at inference time."""
        return decrypt(doc["api_key_encrypted"])

    @staticmethod
    def to_dto(doc: dict, display_name: str) -> ProviderCredentialDto:
        return ProviderCredentialDto(
            provider_id=doc["provider_id"],
            display_name=display_name,
            is_configured=True,
            test_status=doc.get("test_status", "untested"),
            last_test_error=doc.get("last_test_error"),
            created_at=doc["created_at"],
        )
