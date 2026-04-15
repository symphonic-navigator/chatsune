import asyncio
import pytest

from backend.modules.llm._pull_registry import PullTaskRegistry


@pytest.mark.asyncio
async def test_register_creates_handle_with_scope_and_slug():
    reg = PullTaskRegistry()

    async def noop(_pid):
        await asyncio.sleep(10)

    handle = reg.register(scope="connection:c1", slug="llama3.2:3b",
                          coro_factory=noop)
    assert handle.scope == "connection:c1"
    assert handle.slug == "llama3.2:3b"
    assert handle.pull_id
    assert not handle.task.done()
    handle.task.cancel()


@pytest.mark.asyncio
async def test_list_returns_only_matching_scope():
    reg = PullTaskRegistry()

    async def noop(_pid):
        await asyncio.sleep(10)

    a = reg.register(scope="connection:c1", slug="a", coro_factory=noop)
    b = reg.register(scope="connection:c2", slug="b", coro_factory=noop)

    assert [h.pull_id for h in reg.list("connection:c1")] == [a.pull_id]
    assert [h.pull_id for h in reg.list("connection:c2")] == [b.pull_id]

    a.task.cancel()
    b.task.cancel()


@pytest.mark.asyncio
async def test_cancel_cancels_task_and_returns_true():
    reg = PullTaskRegistry()

    async def noop(_pid):
        await asyncio.sleep(10)

    h = reg.register(scope="admin-local", slug="x", coro_factory=noop)
    ok = reg.cancel("admin-local", h.pull_id)
    assert ok
    await asyncio.sleep(0)
    assert h.task.cancelled() or h.task.done()


@pytest.mark.asyncio
async def test_cancel_unknown_returns_false():
    reg = PullTaskRegistry()
    assert reg.cancel("admin-local", "nonexistent") is False


@pytest.mark.asyncio
async def test_completed_task_is_removed_from_registry():
    reg = PullTaskRegistry()

    async def finish_fast(_pid):
        return None

    h = reg.register(scope="admin-local", slug="x", coro_factory=finish_fast)
    await h.task
    await asyncio.sleep(0)
    assert reg.list("admin-local") == []


@pytest.mark.asyncio
async def test_update_status_mutates_last_status():
    reg = PullTaskRegistry()

    async def noop(_pid):
        await asyncio.sleep(10)

    h = reg.register(scope="admin-local", slug="x", coro_factory=noop)
    reg.update_status(h.pull_id, "downloading")
    assert h.last_status == "downloading"
    h.task.cancel()


@pytest.mark.asyncio
async def test_cancel_rejects_wrong_scope():
    """Cancel must only match if the scope also matches — prevents cross-scope cancellation."""
    reg = PullTaskRegistry()

    async def noop(_pid):
        await asyncio.sleep(10)

    h = reg.register(scope="connection:c1", slug="x", coro_factory=noop)
    assert reg.cancel("connection:c2", h.pull_id) is False
    # Still running
    assert not h.task.done()
    h.task.cancel()
