from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.user._models import UserKeysDocument, WrappedDekPair


def _to_mongo(doc: UserKeysDocument) -> dict:
    """Serialise a UserKeysDocument to a plain dict suitable for Motor insert_one.

    Pydantic's model_dump() base64-encodes bytes fields — we must overwrite
    them with their raw values so BSON stores native Binary, not strings.
    """
    raw = doc.model_dump()
    raw["kdf_salt"] = doc.kdf_salt
    for version_key, pair in doc.deks.items():
        raw["deks"][version_key]["wrapped_by_password"] = pair.wrapped_by_password
        raw["deks"][version_key]["wrapped_by_recovery"] = pair.wrapped_by_recovery
    return raw


def _from_mongo(raw: dict) -> UserKeysDocument:
    """Construct a UserKeysDocument from a Motor find result, stripping _id."""
    raw = dict(raw)
    raw.pop("_id", None)
    return UserKeysDocument.model_validate(raw)


class UserKeysRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["user_keys"]

    async def ensure_indexes(self) -> None:
        """Create collection indexes. Safe to call on every startup (idempotent)."""
        await self._collection.create_index("user_id", unique=True)

    async def insert(self, doc: UserKeysDocument, *, session=None) -> None:
        """Insert a new UserKeysDocument. Raises DuplicateKeyError if user_id exists."""
        await self._collection.insert_one(_to_mongo(doc), session=session)

    async def get_by_user_id(self, user_id: str, *, session=None) -> UserKeysDocument | None:
        """Return the key document for a user, or None if not found."""
        raw = await self._collection.find_one({"user_id": user_id}, session=session)
        if raw is None:
            return None
        return _from_mongo(raw)

    async def set_recovery_required(self, user_id: str, *, value: bool) -> None:
        """Set or clear the dek_recovery_required flag on a user's key document."""
        await self._collection.update_one(
            {"user_id": user_id},
            {"$set": {"dek_recovery_required": value, "updated_at": datetime.now(UTC)}},
        )

    async def replace_wrapped_by_password(
        self, user_id: str, *, version: int, blob: bytes
    ) -> None:
        """Replace the password-wrapped DEK blob for a specific DEK version.

        The recovery-wrapped blob is left untouched.
        """
        now = datetime.now(UTC)
        await self._collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    f"deks.{version}.wrapped_by_password": blob,
                    f"deks.{version}.created_at": now,
                    "updated_at": now,
                }
            },
        )

    async def replace_wrapped_by_recovery(
        self, user_id: str, *, version: int, blob: bytes
    ) -> None:
        """Replace the recovery-wrapped DEK blob for a specific DEK version.

        The password-wrapped blob is left untouched. Used when the user
        regenerates their recovery key without changing the password.
        """
        now = datetime.now(UTC)
        await self._collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    f"deks.{version}.wrapped_by_recovery": blob,
                    f"deks.{version}.created_at": now,
                    "updated_at": now,
                }
            },
        )

    async def replace_both_wraps(
        self,
        user_id: str,
        *,
        version: int,
        wrapped_by_password: bytes,
        wrapped_by_recovery: bytes,
    ) -> None:
        """Replace both wrapped DEK blobs for a specific version in one write.

        Used by key-rotation and recovery flows that need to rewrite both
        wraps atomically (from the caller's perspective).
        """
        now = datetime.now(UTC)
        await self._collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    f"deks.{version}.wrapped_by_password": wrapped_by_password,
                    f"deks.{version}.wrapped_by_recovery": wrapped_by_recovery,
                    f"deks.{version}.created_at": now,
                    "updated_at": now,
                }
            },
        )
