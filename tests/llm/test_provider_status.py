import pytest
from fakeredis.aioredis import FakeRedis

from backend.modules.llm._provider_status import (
    get_all_statuses,
    set_status,
)


@pytest.mark.asyncio
async def test_set_and_read_status():
    redis = FakeRedis()
    changed = await set_status(redis, "ollama_local", available=True, model_count=3)
    assert changed is True  # first write is always a change

    snap = await get_all_statuses(redis, ["ollama_local", "ollama_cloud"])
    assert snap == {"ollama_local": True, "ollama_cloud": False}


@pytest.mark.asyncio
async def test_status_change_only_signals_when_flipped():
    redis = FakeRedis()
    await set_status(redis, "ollama_local", available=True, model_count=2)
    again = await set_status(redis, "ollama_local", available=True, model_count=5)
    assert again is False  # model_count alone does not flip availability

    flipped = await set_status(redis, "ollama_local", available=False, model_count=0)
    assert flipped is True
