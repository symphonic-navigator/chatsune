"""Refcounted per-user refresher task lifecycle."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.modules.llm._metadata_refresher import ModelCacheRefresher


@pytest.fixture
def refresher(monkeypatch) -> ModelCacheRefresher:
    r = ModelCacheRefresher()

    async def _noop_iteration(user_id: str) -> None:
        # Park indefinitely so the task stays alive until cancelled.
        await asyncio.Event().wait()

    monkeypatch.setattr(r, "_run_user_iteration", AsyncMock(side_effect=_noop_iteration))
    return r


@pytest.mark.asyncio
async def test_ensure_creates_task_on_first_call(refresher):
    await refresher.ensure_user_task("user-a")
    assert refresher.has_active_task("user-a")
    await refresher.release_user_task("user-a")


@pytest.mark.asyncio
async def test_ensure_is_idempotent(refresher):
    await refresher.ensure_user_task("user-a")
    task_before = refresher._tasks["user-a"]

    await refresher.ensure_user_task("user-a")
    task_after = refresher._tasks["user-a"]

    assert task_before is task_after
    assert refresher._refcounts["user-a"] == 2

    await refresher.release_user_task("user-a")
    assert refresher.has_active_task("user-a")  # one ref left
    await refresher.release_user_task("user-a")
    assert not refresher.has_active_task("user-a")


@pytest.mark.asyncio
async def test_release_below_zero_is_safe(refresher):
    # Releasing a user we never ensured must not raise:
    await refresher.release_user_task("nobody")
    assert not refresher.has_active_task("nobody")
