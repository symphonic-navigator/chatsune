"""Redis persistence for nano-gpt's pair map.

Nano-GPT expresses thinking capability as *pairs* of upstream slugs
(``base`` + ``base:thinking``, or rare inverted ``base`` +
``base-nothinking``). ``NanoGptHttpAdapter.fetch_models`` builds the
pair map at catalogue time; a future ``stream_completion`` reads it at
request time to pick the correct upstream slug.

The shared ``ModelMetaDto`` intentionally does NOT carry the pair slugs
— that data is adapter-specific and lives here, scoped per connection,
with a 30-minute TTL matching the sibling metadata cache in
``backend/modules/llm/_metadata.py``.
"""
import json

from redis.asyncio import Redis

PAIR_MAP_TTL_SECONDS = 30 * 60

PairMap = dict[str, dict[str, str | None]]


def _key(connection_id: str) -> str:
    return f"nano_gpt:pair_map:{connection_id}"


async def save_pair_map(
    redis: Redis, *, connection_id: str, pair_map: PairMap,
) -> None:
    await redis.set(
        _key(connection_id),
        json.dumps(pair_map),
        ex=PAIR_MAP_TTL_SECONDS,
    )


async def load_pair_map(
    redis: Redis, *, connection_id: str,
) -> PairMap:
    raw = await redis.get(_key(connection_id))
    if raw is None:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)
