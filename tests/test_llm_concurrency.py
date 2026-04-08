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
