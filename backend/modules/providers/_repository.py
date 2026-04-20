"""Repository for premium_provider_accounts collection."""
from datetime import UTC, datetime
from uuid import uuid4

from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.config import settings
from backend.modules.providers._registry import get as get_definition
from shared.dtos.providers import PremiumProviderAccountDto

COLLECTION = "premium_provider_accounts"


def _fernet() -> Fernet:
    return Fernet(settings.encryption_key.encode())


def _secret_fields(provider_id: str) -> frozenset[str]:
    defn = get_definition(provider_id)
    return defn.secret_fields if defn else frozenset()


def _split_config(provider_id: str, config: dict) -> tuple[dict, dict]:
    secrets = _secret_fields(provider_id)
    plain: dict = {}
    encrypted: dict = {}
    f = _fernet()
    for k, v in config.items():
        if k in secrets:
            if v is None or v == "":
                continue
            encrypted[k] = f.encrypt(str(v).encode()).decode()
        else:
            plain[k] = v
    return plain, encrypted


def _redact_config(provider_id: str, plain: dict, encrypted: dict) -> dict:
    secrets = _secret_fields(provider_id)
    out = dict(plain)
    for k in secrets:
        out[k] = {"is_set": k in encrypted}
    return out


class PremiumProviderAccountRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._col = db[COLLECTION]

    async def create_indexes(self) -> None:
        await self._col.create_index(
            [("user_id", 1), ("provider_id", 1)], unique=True,
        )
        await self._col.create_index([("user_id", 1), ("created_at", 1)])

    async def upsert(
        self, user_id: str, provider_id: str, config: dict,
    ) -> dict:
        existing = await self._col.find_one(
            {"user_id": user_id, "provider_id": provider_id},
            {"config_encrypted": 1, "_id": 0},
        )
        existing_enc = (existing or {}).get("config_encrypted") or {}
        plain, encrypted = _split_config(provider_id, config)
        secrets = _secret_fields(provider_id)

        # Secret merge semantics: a new plaintext value overwrites; an empty
        # or absent secret field preserves the existing value. There is no
        # explicit-clear path through upsert — deleting credentials is done
        # via `delete()` (remove the whole account).
        merged_enc = dict(existing_enc)
        for k in secrets:
            if k in encrypted:
                merged_enc[k] = encrypted[k]

        now = datetime.now(UTC)
        set_on_insert = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "provider_id": provider_id,
            "created_at": now,
            "last_test_status": None,
            "last_test_error": None,
            "last_test_at": None,
        }
        set_fields = {
            "config": plain,
            "config_encrypted": merged_enc,
            "updated_at": now,
        }
        return await self._col.find_one_and_update(
            {"user_id": user_id, "provider_id": provider_id},
            {"$set": set_fields, "$setOnInsert": set_on_insert},
            upsert=True,
            return_document=True,
        )

    async def find(self, user_id: str, provider_id: str) -> dict | None:
        return await self._col.find_one(
            {"user_id": user_id, "provider_id": provider_id},
        )

    async def list_for_user(self, user_id: str) -> list[dict]:
        return [
            d async for d in self._col.find({"user_id": user_id}).sort("created_at", 1)
        ]

    async def delete(self, user_id: str, provider_id: str) -> bool:
        res = await self._col.delete_one(
            {"user_id": user_id, "provider_id": provider_id},
        )
        return res.deleted_count > 0

    async def delete_all_for_user(self, user_id: str) -> int:
        res = await self._col.delete_many({"user_id": user_id})
        return res.deleted_count

    async def update_test_status(
        self, user_id: str, provider_id: str, *, status: str, error: str | None,
    ) -> dict | None:
        now = datetime.now(UTC)
        return await self._col.find_one_and_update(
            {"user_id": user_id, "provider_id": provider_id},
            {"$set": {
                "last_test_status": status,
                "last_test_error": error,
                "last_test_at": now,
                "updated_at": now,
            }},
            return_document=True,
        )

    @staticmethod
    def get_decrypted_secret(doc: dict, field: str) -> str | None:
        enc = doc.get("config_encrypted") or {}
        if field not in enc:
            return None
        return _fernet().decrypt(enc[field].encode()).decode()

    @staticmethod
    def to_dto(doc: dict) -> PremiumProviderAccountDto:
        return PremiumProviderAccountDto(
            provider_id=doc["provider_id"],
            config=_redact_config(
                doc["provider_id"],
                doc.get("config", {}) or {},
                doc.get("config_encrypted", {}) or {},
            ),
            last_test_status=doc.get("last_test_status"),
            last_test_error=doc.get("last_test_error"),
            last_test_at=doc.get("last_test_at"),
        )
