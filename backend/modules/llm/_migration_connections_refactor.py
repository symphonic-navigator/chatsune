"""One-shot cleanup for the Connections Refactor (v1).

Runs once per database on startup, gated by a marker document in the
``_migrations`` collection. Idempotent: re-runs are no-ops.

The legacy provider-era data model (per-user credentials, model curations,
per-user model configs) is replaced by the new Connections model. On first
boot after the refactor, this module:

* drops the obsolete MongoDB collections,
* unwires every persona's ``model_unique_id`` (old IDs are no longer valid),
* deletes legacy Redis cache keys (model lists, provider statuses),
* writes a marker document so subsequent boots skip all of the above.

Failure is intentionally not caught here — the caller (startup lifespan)
must abort if this does not complete, otherwise the app would run against
an inconsistent mix of old and new state.
"""

import logging
from datetime import UTC, datetime

from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

_log = logging.getLogger(__name__)

_MARKER_ID = "connections_refactor_v1"


async def run_if_needed(db: AsyncIOMotorDatabase, redis: Redis) -> None:
    """Run the one-shot cleanup unless the marker is already present."""
    marker = await db["_migrations"].find_one({"_id": _MARKER_ID})
    if marker is not None:
        return

    _log.warning("connections_refactor_v1: running one-shot cleanup")

    # Drop obsolete collections owned by the provider-era LLM module.
    await db["llm_user_credentials"].drop()
    _log.warning("connections_refactor_v1: dropped llm_user_credentials")
    await db["llm_model_curations"].drop()
    _log.warning("connections_refactor_v1: dropped llm_model_curations")
    await db["llm_user_model_configs"].drop()
    _log.warning("connections_refactor_v1: dropped llm_user_model_configs")

    # Null out stale persona references — the old <provider>:<slug> IDs are
    # no longer resolvable under the Connections model.
    result = await db["personas"].update_many(
        {}, {"$set": {"model_unique_id": None}},
    )
    _log.warning(
        "connections_refactor_v1: unwired %d personas",
        result.modified_count,
    )

    # Clear legacy Redis cache keys. SCAN (not KEYS) to avoid blocking Redis
    # on large keyspaces — ``scan_iter`` paginates transparently.
    deleted_models = 0
    async for key in redis.scan_iter(match="llm:models:*", count=100):
        await redis.delete(key)
        deleted_models += 1
    _log.warning(
        "connections_refactor_v1: deleted %d llm:models:* redis keys",
        deleted_models,
    )

    deleted_status = 0
    async for key in redis.scan_iter(match="llm:provider:status:*", count=100):
        await redis.delete(key)
        deleted_status += 1
    _log.warning(
        "connections_refactor_v1: deleted %d llm:provider:status:* redis keys",
        deleted_status,
    )

    await db["_migrations"].insert_one(
        {"_id": _MARKER_ID, "at": datetime.now(UTC)},
    )
    _log.warning("connections_refactor_v1: cleanup complete")
