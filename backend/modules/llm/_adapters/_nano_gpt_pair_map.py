"""Redis persistence for nano-gpt's pair map.

Nano-GPT expresses thinking capability through two distinct mechanisms.
Some models come as a *pair* of upstream slugs (``base`` +
``base:thinking``, or rare inverted ``base`` + ``base-nothinking``).
Others arrive as a singleton with ``capabilities.reasoning == true``
and switch via a flag in the request body. The pair map captures both
shapes via a ``switching_mode`` discriminator.

``NanoGptHttpAdapter.fetch_models`` builds the pair map at catalogue
time; ``stream_completion`` reads it at request time to pick the
correct upstream slug AND decide whether to send the body flag.

The shared ``ModelMetaDto`` intentionally does NOT carry the pair slugs
— that data is adapter-specific and lives here, scoped per connection,
with a 30-minute TTL matching the sibling metadata cache in
``backend/modules/llm/_metadata.py``.

Cache key carries an explicit ``v2`` revision: the value shape gained
``switching_mode`` and any pre-revision entry would be misinterpreted.
``v1`` keys expire on their own TTL.
"""
import json

from redis.asyncio import Redis

PAIR_MAP_TTL_SECONDS = 30 * 60

# Per-entry shape: {"non_thinking_slug": str, "thinking_slug": str | None,
# "switching_mode": "slug" | "flag" | "none"}.
PairMap = dict[str, dict[str, str | None]]


def _key(connection_id: str) -> str:
    return f"nano_gpt:pair_map:v2:{connection_id}"


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
    parsed = json.loads(raw)
    # Defensive read: if any entry is missing ``switching_mode`` (a
    # stale v1-shape value somehow living under a v2 key), treat the
    # whole map as a cache miss so the adapter re-fetches.
    for value in parsed.values():
        if not isinstance(value, dict) or "switching_mode" not in value:
            return {}
    return parsed
