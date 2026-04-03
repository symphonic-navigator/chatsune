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
        existing = await self.find(user_id, provider_id)
        if existing:
            await self._collection.update_one(
                {"_id": existing["_id"]},
                {"$set": {"api_key_encrypted": encrypted, "updated_at": now}},
            )
            return await self.find(user_id, provider_id)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "provider_id": provider_id,
            "api_key_encrypted": encrypted,
            "created_at": now,
            "updated_at": now,
        }
        await self._collection.insert_one(doc)
        return doc

    async def delete(self, user_id: str, provider_id: str) -> bool:
        result = await self._collection.delete_one(
            {"user_id": user_id, "provider_id": provider_id}
        )
        return result.deleted_count > 0

    async def list_for_user(self, user_id: str) -> list[dict]:
        cursor = self._collection.find({"user_id": user_id})
        return await cursor.to_list(length=100)

    def get_raw_key(self, doc: dict) -> str:
        """Decrypt and return the raw API key. Use only at inference time."""
        return decrypt(doc["api_key_encrypted"])

    @staticmethod
    def to_dto(doc: dict, display_name: str) -> ProviderCredentialDto:
        return ProviderCredentialDto(
            provider_id=doc["provider_id"],
            display_name=display_name,
            is_configured=True,
            created_at=doc["created_at"],
        )
