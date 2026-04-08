"""Regression tests for the heartbeat/cancel dict race condition (C-002).

These tests exercise concurrent mutation of the four module-level dicts in
``backend.modules.chat._orchestrator`` via ``record_heartbeat`` and
``cancel_all_for_user``. Before the ``_heartbeat_lock`` was introduced, this
pattern could race and surface as ``KeyError`` or leave stale entries in the
dicts. The test accesses the internals directly on purpose — it is a
regression test, not an API test.
"""

import asyncio

import pytest

from backend.modules.chat import _orchestrator as orch


@pytest.mark.asyncio
async def test_record_heartbeat_and_cancel_race_is_clean() -> None:
    user_id = "user-race"
    iterations = 200

    for i in range(iterations):
        cid = f"corr-{i}"
        # Seed an in-flight inference entry as run_inference would.
        async with orch._heartbeat_lock:
            orch._cancel_events[cid] = asyncio.Event()
            orch._last_heartbeat[cid] = 0.0
            orch._cancel_user_ids[cid] = user_id

        async def hammer_heartbeat() -> None:
            for _ in range(5):
                await orch.record_heartbeat(user_id, cid)
                await asyncio.sleep(0)

        async def hammer_cancel() -> None:
            for _ in range(5):
                await orch.cancel_all_for_user(user_id)
                await asyncio.sleep(0)

        await asyncio.gather(
            hammer_heartbeat(),
            hammer_cancel(),
            hammer_heartbeat(),
            hammer_cancel(),
        )

        # Simulate run_inference finally-block cleanup.
        async with orch._heartbeat_lock:
            orch._cancel_events.pop(cid, None)
            orch._last_heartbeat.pop(cid, None)
            orch._cancel_user_ids.pop(cid, None)
            orch._heartbeat_watchdogs.pop(cid, None)

    # After the loop, none of the exercised correlation ids should remain.
    for i in range(iterations):
        cid = f"corr-{i}"
        assert cid not in orch._cancel_events
        assert cid not in orch._last_heartbeat
        assert cid not in orch._cancel_user_ids
        assert cid not in orch._heartbeat_watchdogs
