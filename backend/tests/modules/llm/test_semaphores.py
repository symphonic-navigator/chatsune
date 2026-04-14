import asyncio

import pytest

from backend.modules.llm._semaphores import ConnectionSemaphoreRegistry


def test_returns_stable_semaphore_for_same_id_and_size():
    r = ConnectionSemaphoreRegistry()
    a = r.get("c1", 3)
    b = r.get("c1", 3)
    assert a is b


def test_recreates_on_size_change():
    r = ConnectionSemaphoreRegistry()
    a = r.get("c1", 3)
    b = r.get("c1", 5)
    assert a is not b


def test_evict_removes_entry():
    r = ConnectionSemaphoreRegistry()
    a = r.get("c1", 3)
    r.evict("c1")
    b = r.get("c1", 3)
    assert a is not b


def test_size_clamped_to_minimum_one():
    r = ConnectionSemaphoreRegistry()
    sem = r.get("c1", 0)
    # Semaphore built with _value=1 — can acquire exactly once without await.
    assert sem._value == 1
