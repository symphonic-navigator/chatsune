from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from redis.asyncio import Redis

from backend.config import settings

_mongo_client: AsyncIOMotorClient | None = None
_redis_client: Redis | None = None


async def connect_db() -> None:
    global _mongo_client, _redis_client
    _mongo_client = AsyncIOMotorClient(settings.mongodb_uri)
    _redis_client = Redis.from_url(settings.redis_uri, decode_responses=True)


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
