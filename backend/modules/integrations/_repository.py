"""MongoDB persistence for per-user integration configurations."""

import logging

from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.config import settings
from backend.modules.integrations._registry import get as get_definition

_log = logging.getLogger(__name__)

COLLECTION = "user_integration_configs"


def _fernet() -> Fernet:
    return Fernet(settings.encryption_key.encode())


def _encrypt(v: str) -> str:
    return _fernet().encrypt(v.encode()).decode()


def _decrypt(v: str) -> str:
    return _fernet().decrypt(v.encode()).decode()


def _secret_field_keys(integration_id: str) -> set[str]:
    defn = get_definition(integration_id)
    if defn is None:
        return set()
    return {f["key"] for f in defn.config_fields if f.get("secret")}


def _split_config(integration_id: str, config: dict) -> tuple[dict, dict]:
    """Split a flat config dict into (plain, encrypted) based on secret fields."""
    secret_keys = _secret_field_keys(integration_id)
    plain: dict = {}
    encrypted: dict = {}
    for k, v in config.items():
        if k in secret_keys:
            if v is None or v == "":
                continue
            encrypted[k] = _encrypt(str(v))
        else:
            plain[k] = v
    return plain, encrypted


def _redact_config(integration_id: str, plain: dict, encrypted: dict) -> dict:
    """Return a config view with secrets replaced by {is_set: bool}."""
    secret_keys = _secret_field_keys(integration_id)
    out = dict(plain)
    for k in secret_keys:
        out[k] = {"is_set": k in encrypted}
    return out


class IntegrationRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self._col = db[COLLECTION]

    async def init_indexes(self) -> None:
        await self._col.create_index(
            [("user_id", 1), ("integration_id", 1)],
            unique=True,
        )

    async def get_user_configs(self, user_id: str) -> list[dict]:
        """Return all integration configs for a user (secrets redacted)."""
        cursor = self._col.find({"user_id": user_id}, {"_id": 0})
        docs = await cursor.to_list(length=100)
        return [self._redact_doc(d) for d in docs]

    async def get_user_config(self, user_id: str, integration_id: str) -> dict | None:
        """Return a single integration config (secrets redacted)."""
        doc = await self._col.find_one(
            {"user_id": user_id, "integration_id": integration_id},
            {"_id": 0},
        )
        return self._redact_doc(doc) if doc else None

    @staticmethod
    def _redact_doc(doc: dict) -> dict:
        out = dict(doc)
        out["config"] = _redact_config(
            doc["integration_id"],
            doc.get("config", {}) or {},
            doc.get("config_encrypted", {}) or {},
        )
        out.pop("config_encrypted", None)
        return out

    async def delete_all_for_user(self, user_id: str) -> int:
        """Delete every integration config owned by ``user_id``.

        Used by the user self-delete cascade (right-to-be-forgotten).
        """
        res = await self._col.delete_many({"user_id": user_id})
        return res.deleted_count

    async def upsert_config(
        self,
        user_id: str,
        integration_id: str,
        enabled: bool,
        config: dict,
    ) -> dict:
        """Create or update a user's integration config.

        Secret fields are encrypted. Absent secret field → preserve existing.
        Empty-string secret field → explicit clear.
        """
        existing = await self._col.find_one(
            {"user_id": user_id, "integration_id": integration_id},
            {"config_encrypted": 1, "_id": 0},
        )
        existing_encrypted: dict = (existing or {}).get("config_encrypted", {}) or {}

        plain, encrypted = _split_config(integration_id, config)
        secret_keys = _secret_field_keys(integration_id)

        merged_encrypted = dict(existing_encrypted)
        for key in secret_keys:
            if key in encrypted:
                merged_encrypted[key] = encrypted[key]
            elif key in config and (config[key] is None or config[key] == ""):
                merged_encrypted.pop(key, None)

        doc = {
            "user_id": user_id,
            "integration_id": integration_id,
            "enabled": enabled,
            "config": plain,
            "config_encrypted": merged_encrypted,
        }
        await self._col.update_one(
            {"user_id": user_id, "integration_id": integration_id},
            {"$set": doc},
            upsert=True,
        )
        _log.info(
            "Upserted integration config: user=%s integration=%s enabled=%s",
            user_id, integration_id, enabled,
        )
        return self._redact_doc(doc)

    async def get_decrypted_secret(
        self, user_id: str, integration_id: str, field: str,
    ) -> str | None:
        doc = await self._col.find_one(
            {"user_id": user_id, "integration_id": integration_id},
            {"config_encrypted": 1, "_id": 0},
        )
        if not doc:
            return None
        enc = doc.get("config_encrypted") or {}
        if field not in enc:
            return None
        return _decrypt(enc[field])

    async def get_all_decrypted_secrets(
        self, user_id: str, integration_id: str,
    ) -> dict[str, str]:
        doc = await self._col.find_one(
            {"user_id": user_id, "integration_id": integration_id},
            {"config_encrypted": 1, "_id": 0},
        )
        if not doc:
            return {}
        enc = doc.get("config_encrypted", {}) or {}
        return {k: _decrypt(v) for k, v in enc.items()}

    async def list_enabled_with_secrets(
        self, user_id: str,
    ) -> list[tuple[str, dict[str, str]]]:
        cursor = self._col.find(
            {"user_id": user_id, "enabled": True},
            {"_id": 0, "integration_id": 1, "config_encrypted": 1},
        )
        out: list[tuple[str, dict[str, str]]] = []
        async for doc in cursor:
            enc = doc.get("config_encrypted", {}) or {}
            if not enc:
                continue
            out.append((
                doc["integration_id"],
                {k: _decrypt(v) for k, v in enc.items()},
            ))
        return out
