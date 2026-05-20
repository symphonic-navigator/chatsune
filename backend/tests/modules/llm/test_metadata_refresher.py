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


from datetime import UTC, datetime
from unittest.mock import patch

from backend.modules.llm._adapters._types import ResolvedConnection


def _make_resolved(adapter_type: str, conn_id: str) -> ResolvedConnection:
    now = datetime.now(UTC)
    return ResolvedConnection(
        id=conn_id,
        user_id="user-a",
        adapter_type=adapter_type,
        display_name=conn_id,
        slug=conn_id,
        config={"url": "http://x", "api_key": "k"},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_iteration_refreshes_all_connections_and_premium_accounts():
    r = ModelCacheRefresher()

    conn = _make_resolved("ollama_http", "conn-1")
    premium = _make_resolved("xai_http", "premium:xai")

    refresh_conn = AsyncMock()
    refresh_premium = AsyncMock()

    with (
        patch.object(r, "_resolve_user_connections", AsyncMock(return_value=[conn])),
        patch.object(r, "_resolve_user_premium_accounts",
                     AsyncMock(return_value=[("xai", premium)])),
        patch.object(r, "_get_redis", lambda: AsyncMock()),
        patch.object(r, "_get_event_bus", lambda: AsyncMock()),
        patch.object(r, "_get_adapter_class", lambda _t: AsyncMock()),
        patch(
            "backend.modules.llm._metadata_refresher._refresh_connection_into_cache",
            refresh_conn,
        ),
        patch(
            "backend.modules.llm._metadata_refresher._refresh_premium_into_cache",
            refresh_premium,
        ),
    ):
        await r._run_user_iteration("user-a")

    refresh_conn.assert_awaited_once()
    refresh_premium.assert_awaited_once()


@pytest.mark.asyncio
async def test_iteration_continues_when_one_target_fails():
    r = ModelCacheRefresher()
    conn_ok = _make_resolved("ollama_http", "conn-ok")
    conn_bad = _make_resolved("ollama_http", "conn-bad")

    async def fake_refresh(c, *_args, **_kwargs):
        if c.id == "conn-bad":
            raise RuntimeError("upstream down")

    with (
        patch.object(r, "_resolve_user_connections",
                     AsyncMock(return_value=[conn_bad, conn_ok])),
        patch.object(r, "_resolve_user_premium_accounts",
                     AsyncMock(return_value=[])),
        patch.object(r, "_get_redis", lambda: AsyncMock()),
        patch.object(r, "_get_event_bus", lambda: AsyncMock()),
        patch.object(r, "_get_adapter_class", lambda _t: AsyncMock()),
        patch(
            "backend.modules.llm._metadata_refresher._refresh_connection_into_cache",
            AsyncMock(side_effect=fake_refresh),
        ) as mock_refresh,
    ):
        await r._run_user_iteration("user-a")
    assert mock_refresh.await_count == 2  # both attempted, one raised


@pytest.mark.asyncio
async def test_trigger_connection_spawns_task_and_returns_immediately():
    r = ModelCacheRefresher()
    fake_conn = _make_resolved("ollama_http", "conn-x")

    refresh_called = asyncio.Event()

    async def fake_refresh(*_args, **_kwargs):
        refresh_called.set()

    with (
        patch.object(r, "_load_connection",
                     AsyncMock(return_value=fake_conn)),
        patch.object(r, "_get_redis", lambda: AsyncMock()),
        patch.object(r, "_get_event_bus", lambda: AsyncMock()),
        patch.object(r, "_get_adapter_class", lambda _t: AsyncMock()),
        patch(
            "backend.modules.llm._metadata_refresher._refresh_connection_into_cache",
            AsyncMock(side_effect=fake_refresh),
        ),
        patch.object(r, "_publish_connection_refreshed", AsyncMock()),
    ):
        await r.trigger_connection("conn-x")
        # await the spawned task explicitly via the refresher's tracking:
        await asyncio.wait_for(refresh_called.wait(), timeout=1.0)


@pytest.mark.asyncio
async def test_trigger_connection_swallows_errors():
    r = ModelCacheRefresher()
    fake_conn = _make_resolved("ollama_http", "conn-x")

    async def bad_refresh(*_args, **_kwargs):
        raise RuntimeError("upstream down")

    with (
        patch.object(r, "_load_connection",
                     AsyncMock(return_value=fake_conn)),
        patch.object(r, "_get_redis", lambda: AsyncMock()),
        patch.object(r, "_get_event_bus", lambda: AsyncMock()),
        patch.object(r, "_get_adapter_class", lambda _t: AsyncMock()),
        patch(
            "backend.modules.llm._metadata_refresher._refresh_connection_into_cache",
            AsyncMock(side_effect=bad_refresh),
        ),
    ):
        await r.trigger_connection("conn-x")
        # Yield so the spawned task has a chance to fail:
        await asyncio.sleep(0.05)
    # Reaching here without an unhandled-exception warning is the assertion.
