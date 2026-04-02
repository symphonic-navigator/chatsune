import json
from datetime import datetime, timezone

from redis.asyncio import Redis

from backend.config import settings

_KEY_PREFIX = "refresh:"
_USER_INDEX_PREFIX = "user_refresh_tokens:"
_TTL_SECONDS = settings.jwt_refresh_token_expire_days * 86400


class RefreshTokenStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def store(
        self, token: str, user_id: str, session_id: str
    ) -> None:
        data = json.dumps(
            {
                "user_id": user_id,
                "session_id": session_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        pipe = self._redis.pipeline()
        pipe.setex(f"{_KEY_PREFIX}{token}", _TTL_SECONDS, data)
        pipe.sadd(f"{_USER_INDEX_PREFIX}{user_id}", token)
        await pipe.execute()

    async def get(self, token: str) -> dict | None:
        data = await self._redis.get(f"{_KEY_PREFIX}{token}")
        if data is None:
            return None
        return json.loads(data)

    async def consume(self, token: str) -> dict | None:
        data = await self.get(token)
        if data is None:
            return None
        pipe = self._redis.pipeline()
        pipe.delete(f"{_KEY_PREFIX}{token}")
        pipe.srem(f"{_USER_INDEX_PREFIX}{data['user_id']}", token)
        await pipe.execute()
        return data

    async def revoke_all_for_user(self, user_id: str) -> None:
        index_key = f"{_USER_INDEX_PREFIX}{user_id}"
        tokens = await self._redis.smembers(index_key)
        if tokens:
            pipe = self._redis.pipeline()
            for token in tokens:
                pipe.delete(f"{_KEY_PREFIX}{token}")
            pipe.delete(index_key)
            await pipe.execute()
