"""One-shot migration for Premium Provider Accounts (v1).

Gated by a marker document in ``_migrations``. Idempotent — re-runs are no-ops.
"""
import hashlib
import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.config import settings
from backend.modules.providers._repository import PremiumProviderAccountRepository

_log = logging.getLogger(__name__)
_MARKER_ID = "premium_provider_accounts_v1"


def _hash_key_for_audit(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:8]


async def run_if_needed(db: AsyncIOMotorDatabase, _redis=None) -> None:
    marker = await db["_migrations"].find_one({"_id": _MARKER_ID})
    if marker is not None:
        return

    _log.warning("premium_provider_accounts_v1: running one-shot migration")

    await _step_0_import_keys(db)
    await _step_1_rewrite_model_unique_ids(db)
    await _step_2_delete_migrated_connections(db)
    await _step_3_strip_integration_api_keys(db)
    await _step_4_drop_websearch_credentials(db)

    await db["_migrations"].insert_one({
        "_id": _MARKER_ID,
        "applied_at": datetime.now(UTC),
    })
    _log.warning("premium_provider_accounts_v1: done")


async def _step_0_import_keys(db: AsyncIOMotorDatabase) -> None:
    pass     # filled in Task 16


async def _step_1_rewrite_model_unique_ids(db: AsyncIOMotorDatabase) -> None:
    pass     # filled in Task 17


async def _step_2_delete_migrated_connections(db: AsyncIOMotorDatabase) -> None:
    pass     # filled in Task 17


async def _step_3_strip_integration_api_keys(db: AsyncIOMotorDatabase) -> None:
    pass     # filled in Task 17


async def _step_4_drop_websearch_credentials(db: AsyncIOMotorDatabase) -> None:
    await db.drop_collection("websearch_user_credentials")
