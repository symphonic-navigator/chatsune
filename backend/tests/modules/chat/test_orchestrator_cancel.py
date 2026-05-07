"""Tests for session-scoped cancel registry in chat._orchestrator."""

import asyncio
import pytest

from backend.modules.chat._orchestrator import (
    _cancel_events,
    _inflight,
    cancel_all_for_user,
    cancel_inflight_for_session,
    request_cancel,
    _user_has_inflight,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    _cancel_events.clear()
    _inflight.clear()
    yield
    _cancel_events.clear()
    _inflight.clear()


def _register(correlation_id: str, user_id: str, session_id: str) -> asyncio.Event:
    event = asyncio.Event()
    _cancel_events[correlation_id] = event
    _inflight[correlation_id] = (user_id, session_id)
    return event


@pytest.mark.asyncio
async def test_cancel_inflight_for_session_targets_only_matching_session():
    e1 = _register("cor-1", "user-a", "session-x")
    e2 = _register("cor-2", "user-a", "session-y")
    e3 = _register("cor-3", "user-b", "session-x")

    cancelled = await cancel_inflight_for_session("user-a", "session-x")

    assert cancelled == 1
    assert e1.is_set()
    assert not e2.is_set()
    assert not e3.is_set()


@pytest.mark.asyncio
async def test_cancel_all_for_user_still_works_for_admin_use():
    e1 = _register("cor-1", "user-a", "session-x")
    e2 = _register("cor-2", "user-a", "session-y")
    e3 = _register("cor-3", "user-b", "session-x")

    cancelled = await cancel_all_for_user("user-a")

    assert cancelled == 2
    assert e1.is_set()
    assert e2.is_set()
    assert not e3.is_set()


async def test_user_has_inflight_returns_true_when_any_correlation_present():
    assert _user_has_inflight("user-a") is False
    _register("cor-1", "user-a", "session-x")
    assert _user_has_inflight("user-a") is True
    assert _user_has_inflight("user-b") is False


def test_request_cancel_with_user_id_filter_rejects_other_user():
    _register("cor-1", "user-a", "session-x")
    fired = request_cancel("cor-1", user_id="user-b")
    assert fired is False
    assert not _cancel_events["cor-1"].is_set()
