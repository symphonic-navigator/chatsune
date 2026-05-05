import asyncio
import logging
from datetime import timezone

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from redis.asyncio import Redis

from backend.config import settings

_mongo_client: AsyncIOMotorClient | None = None
_redis_client: Redis | None = None

_log = logging.getLogger("chatsune.database")


async def _wait_for_primary(client: AsyncIOMotorClient, timeout_seconds: float = 30.0) -> None:
    """Block until mongod reports writable primary state.

    Single-node replica sets (like mongodb-atlas-local) need a few seconds
    after boot to hold an election. Docker healthchecks that only ping mongod
    go green before the election completes — running any admin command in
    that window yields NotPrimaryOrSecondary (code 13436) and aborts startup.
    """
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    last_error: Exception | None = None
    attempts = 0
    while asyncio.get_event_loop().time() < deadline:
        attempts += 1
        try:
            info = await client.admin.command("hello")
            if info.get("isWritablePrimary"):
                if attempts > 1:
                    _log.info("mongodb primary ready after %d attempts", attempts)
                return
            last_error = RuntimeError(f"mongod reachable but not primary: {info.get('me')!r}")
        except Exception as exc:
            last_error = exc
        await asyncio.sleep(0.5)
    raise RuntimeError(
        f"mongodb did not reach writable primary state within {timeout_seconds}s: {last_error}"
    )


async def connect_db() -> None:
    global _mongo_client, _redis_client
    # BSON dates are stored as UTC instants (no offset on the wire). Production
    # code consistently writes ``datetime.now(timezone.utc)`` so the values
    # going in are tz-aware UTC. ``tz_aware=True`` makes PyMongo decode them
    # back into tz-aware datetimes on read; ``tzinfo=timezone.utc`` pins the
    # decoded instances to UTC, which matches what's actually stored. Without
    # this, Pydantic v2 serialises naive datetimes without an offset suffix
    # and JS clients then interpret backend timestamps as local time.
    _mongo_client = AsyncIOMotorClient(
        settings.mongodb_uri, tz_aware=True, tzinfo=timezone.utc,
    )
    _redis_client = Redis.from_url(settings.redis_uri, decode_responses=True)
    await _wait_for_primary(_mongo_client)


async def disconnect_db() -> None:
    global _mongo_client, _redis_client
    if _mongo_client:
        _mongo_client.close()
    if _redis_client:
        await _redis_client.aclose()


def get_db() -> AsyncIOMotorDatabase:
    return _mongo_client.get_database(settings.mongo_db_name)


def get_client() -> AsyncIOMotorClient:
    return _mongo_client


def get_redis() -> Redis:
    return _redis_client
