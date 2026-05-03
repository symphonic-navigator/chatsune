"""Unit tests for PersonaRepository.bump_last_used.

Uses a hand-rolled mock collection so the test runs on the host without
MongoDB. Exercises the call surface that the public bump_last_used
wraps.
"""
from datetime import datetime, UTC
import os

import pytest

# Set required environment variables before any module imports.
os.environ.setdefault("MASTER_ADMIN_PIN", "000000")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-signing-only")
os.environ.setdefault("ENCRYPTION_KEY", "g25N27YLyaybAXpnYPQTgyMJlwfs6RtWBWBF9DzQ36g=")
os.environ.setdefault("KDF_PEPPER", "UOIjXpkhtqbfBaK608oQBM4s2fUx5vCRD6Y5IMlVCyE=")

from backend.modules.persona._repository import PersonaRepository


class _MockCollection:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict]] = []

    async def update_one(self, filter_: dict, update: dict) -> None:
        self.calls.append((filter_, update))

    async def create_index(self, *args, **kwargs) -> None:  # unused here
        pass


@pytest.mark.asyncio
async def test_bump_last_used_updates_correct_persona():
    mock = _MockCollection()
    repo = PersonaRepository.__new__(PersonaRepository)
    repo._collection = mock  # type: ignore[attr-defined]

    before = datetime.now(UTC)
    await repo.bump_last_used("persona-id-1", "user-id-1")
    after = datetime.now(UTC)

    assert len(mock.calls) == 1
    filter_, update = mock.calls[0]
    assert filter_ == {"_id": "persona-id-1", "user_id": "user-id-1"}
    assert "$set" in update
    assert "last_used_at" in update["$set"]
    stamp = update["$set"]["last_used_at"]
    assert before <= stamp <= after


@pytest.mark.asyncio
async def test_bump_last_used_swallows_no_match():
    """update_one with no matching doc must not raise — Motor returns a
    result with matched_count=0, which we ignore deliberately."""
    mock = _MockCollection()
    repo = PersonaRepository.__new__(PersonaRepository)
    repo._collection = mock  # type: ignore[attr-defined]
    await repo.bump_last_used("missing", "user-id-1")
    assert len(mock.calls) == 1
