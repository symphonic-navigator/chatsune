"""GatewayHandle session-lifecycle field tests."""

import asyncio

import pytest

from backend.modules.tools._mcp_registry import GatewayHandle


def _make_handle(**overrides):
    defaults = dict(
        id="gw-1",
        name="ns",
        url="http://example.com/mcp",
        api_key=None,
        tier="admin",
        tool_definitions=[],
    )
    defaults.update(overrides)
    return GatewayHandle(**defaults)


def test_gateway_handle_defaults_session_id_to_none():
    h = _make_handle()
    assert h.session_id is None


def test_gateway_handle_accepts_explicit_session_id():
    h = _make_handle(session_id="abc-123")
    assert h.session_id == "abc-123"


def test_gateway_handle_init_lock_is_asyncio_lock():
    h = _make_handle()
    assert isinstance(h.init_lock, asyncio.Lock)


def test_gateway_handle_init_locks_are_independent_across_handles():
    a = _make_handle(id="a")
    b = _make_handle(id="b")
    assert a.init_lock is not b.init_lock


@pytest.mark.asyncio
async def test_gateway_handle_init_lock_serialises():
    h = _make_handle()
    order: list[str] = []

    async def critical(label: str, hold: float):
        async with h.init_lock:
            order.append(f"{label}-enter")
            await asyncio.sleep(hold)
            order.append(f"{label}-exit")

    await asyncio.gather(critical("A", 0.02), critical("B", 0.01))
    # A acquires first, B waits — strict interleaving
    assert order == ["A-enter", "A-exit", "B-enter", "B-exit"]
