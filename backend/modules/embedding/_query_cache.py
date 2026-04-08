"""Redis-backed query embedding cache.

Count-bounded LRU-by-insertion cache. See INSIGHTS.md INS-013.
"""

import base64
import hashlib
import logging
import struct
import time

from redis.asyncio import Redis

_log = logging.getLogger("chatsune.embedding.cache")

_INDEX_KEY = "emb:_index"


def _encode_vector(vector: list[float]) -> str:
    return base64.b64encode(struct.pack(f"{len(vector)}f", *vector)).decode("ascii")


def _decode_vector(value: str) -> list[float]:
    raw = base64.b64decode(value)
    return list(struct.unpack(f"{len(raw) // 4}f", raw))


class QueryCache:
    def __init__(self, redis: Redis, model_name: str, max_entries: int) -> None:
        self._redis = redis
        self._model_name = model_name
        self._max_entries = max_entries

    def normalize(self, query: str) -> str:
        return " ".join(query.strip().lower().split())

    def make_key(self, normalized_query: str) -> str:
        digest = hashlib.sha256(normalized_query.encode()).hexdigest()
        return f"emb:{self._model_name}:{digest}"

    async def get(self, normalized_query: str) -> list[float] | None:
        try:
            key = self.make_key(normalized_query)
            value = await self._redis.get(key)
            if value is None:
                return None
            return _decode_vector(value)
        except Exception:
            _log.warning("query cache get failed", exc_info=True)
            return None

    async def set(self, normalized_query: str, vector: list[float]) -> None:
        try:
            key = self.make_key(normalized_query)
            encoded = _encode_vector(vector)
            now = int(time.time() * 1000)

            async with self._redis.pipeline(transaction=True) as p:
                p.set(key, encoded)
                p.zadd(_INDEX_KEY, {key: now})
                await p.execute()

            overflow = await self._redis.zcard(_INDEX_KEY) - self._max_entries
            if overflow > 0:
                evicted = await self._redis.zrange(_INDEX_KEY, 0, overflow - 1)
                if evicted:
                    await self._redis.delete(*evicted)
                    await self._redis.zrem(_INDEX_KEY, *evicted)
        except Exception:
            _log.warning("query cache set failed", exc_info=True)
