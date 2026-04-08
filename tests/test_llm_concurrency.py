import asyncio
import pytest

from backend.modules.llm._concurrency import (
    ConcurrencyPolicy,
    InferenceLockRegistry,
)


class _AdapterNone:
    provider_id = "x"
    concurrency_policy = ConcurrencyPolicy.NONE


class _AdapterGlobal:
    provider_id = "ollama_local"
    concurrency_policy = ConcurrencyPolicy.GLOBAL


class _AdapterPerUser:
    provider_id = "per_user_provider"
    concurrency_policy = ConcurrencyPolicy.PER_USER


def test_none_policy_returns_no_lock():
    reg = InferenceLockRegistry()
    assert reg.lock_for(_AdapterNone, user_id="u1") is None


def test_global_policy_returns_same_lock_for_all_users():
    reg = InferenceLockRegistry()
    a = reg.lock_for(_AdapterGlobal, user_id="u1")
    b = reg.lock_for(_AdapterGlobal, user_id="u2")
    assert a is b
    assert isinstance(a, asyncio.Lock)


def test_per_user_policy_returns_distinct_locks_per_user():
    reg = InferenceLockRegistry()
    a = reg.lock_for(_AdapterPerUser, user_id="u1")
    b = reg.lock_for(_AdapterPerUser, user_id="u2")
    c = reg.lock_for(_AdapterPerUser, user_id="u1")
    assert a is not b
    assert a is c


async def test_global_lock_serialises_parallel_acquires(monkeypatch):
    """Two tasks against the same GLOBAL lock run sequentially."""
    from backend.modules.llm._concurrency import (
        ConcurrencyPolicy,
        InferenceLockRegistry,
    )

    class _FakeAdapter:
        provider_id = "fake_local"
        concurrency_policy = ConcurrencyPolicy.GLOBAL

    reg = InferenceLockRegistry()
    lock = reg.lock_for(_FakeAdapter, user_id="u1")
    assert lock is not None

    entered: list[int] = []
    released = asyncio.Event()

    async def stream_a():
        async with lock:
            entered.append(1)
            await released.wait()

    async def stream_b():
        async with lock:
            entered.append(2)

    task_a = asyncio.create_task(stream_a())
    await asyncio.sleep(0.01)
    task_b = asyncio.create_task(stream_b())
    await asyncio.sleep(0.01)

    assert entered == [1]
    released.set()
    await asyncio.gather(task_a, task_b)
    assert entered == [1, 2]
