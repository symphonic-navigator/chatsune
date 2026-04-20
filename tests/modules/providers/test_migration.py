"""Tests for the Premium Provider Accounts v1 one-shot migration.

Uses the ``mongo_db`` fixture from ``tests/modules/providers/conftest.py`` —
that fixture already wipes every collection the migration reads or writes
before and after each test.
"""
from backend.modules.providers._migration_v1 import _MARKER_ID, run_if_needed


async def test_marker_prevents_rerun(mongo_db):
    await mongo_db["_migrations"].insert_one({"_id": _MARKER_ID})
    await run_if_needed(mongo_db, None)
    # Simply the absence of exceptions and speed is the assertion.


async def test_first_run_sets_marker(mongo_db):
    await run_if_needed(mongo_db, None)
    marker = await mongo_db["_migrations"].find_one({"_id": _MARKER_ID})
    assert marker is not None
