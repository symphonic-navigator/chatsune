"""Tests for ``ChatRepository.list_messages_tail``.

Sessions that exceed ``LIST_MESSAGES_CAP`` previously had their NEWEST
messages silently dropped by ``list_messages`` (sort ascending +
``to_list(length=cap)``). ``list_messages_tail`` flips that around so
inference history-loading sees the most recent ``max_count`` entries.

The test runs entirely on host with a minimal in-memory fake of the
motor cursor / collection surface — no MongoDB connection required.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from backend.modules.chat._repository import LIST_MESSAGES_CAP, ChatRepository


class _FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def sort(self, key: str, direction: int) -> "_FakeCursor":
        self._docs = sorted(
            self._docs, key=lambda d: d[key], reverse=(direction == -1),
        )
        return self

    def limit(self, n: int) -> "_FakeCursor":
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: int | None = None) -> list[dict]:
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class _FakeMessages:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def find(self, filter_: dict) -> _FakeCursor:
        session_id = filter_["session_id"]
        return _FakeCursor(
            [deepcopy(d) for d in self._docs if d["session_id"] == session_id]
        )


class _FakeDb:
    def __init__(self, messages: _FakeMessages) -> None:
        self._messages = messages

    def __getitem__(self, name: str):
        if name == "chat_messages":
            return self._messages
        # ``ChatRepository.__init__`` also touches ``chat_sessions`` —
        # return an empty fake so the constructor doesn't blow up.
        return _FakeMessages([])


def _make_docs(session_id: str, n: int) -> list[dict]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        {
            "_id": f"msg-{i:05d}",
            "session_id": session_id,
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"message {i}",
            "created_at": base + timedelta(seconds=i),
        }
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_list_messages_tail_returns_newest_in_ascending_order():
    """A session with 5001 messages must yield exactly LIST_MESSAGES_CAP
    docs covering indices 1..5000, sorted ascending. Index 0 (the very
    oldest) is the one that gets dropped — NOT index 5000 (newest)."""
    session_id = "sess-1"
    docs = _make_docs(session_id, LIST_MESSAGES_CAP + 1)
    repo = ChatRepository(_FakeDb(_FakeMessages(docs)))  # type: ignore[arg-type]

    result = await repo.list_messages_tail(session_id)

    assert len(result) == LIST_MESSAGES_CAP
    # Ascending order preserved.
    assert [d["_id"] for d in result] == [
        f"msg-{i:05d}" for i in range(1, LIST_MESSAGES_CAP + 1)
    ]
    # Oldest message dropped, newest message kept.
    assert result[0]["_id"] == "msg-00001"
    assert result[-1]["_id"] == f"msg-{LIST_MESSAGES_CAP:05d}"


@pytest.mark.asyncio
async def test_list_messages_tail_below_cap_returns_all():
    """When the session is below the cap, every message is returned in
    ascending order — no truncation."""
    session_id = "sess-2"
    docs = _make_docs(session_id, 10)
    repo = ChatRepository(_FakeDb(_FakeMessages(docs)))  # type: ignore[arg-type]

    result = await repo.list_messages_tail(session_id)

    assert len(result) == 10
    assert [d["_id"] for d in result] == [f"msg-{i:05d}" for i in range(10)]


@pytest.mark.asyncio
async def test_list_messages_tail_respects_explicit_max_count():
    """``max_count`` overrides the default cap."""
    session_id = "sess-3"
    docs = _make_docs(session_id, 20)
    repo = ChatRepository(_FakeDb(_FakeMessages(docs)))  # type: ignore[arg-type]

    result = await repo.list_messages_tail(session_id, max_count=5)

    assert len(result) == 5
    # Newest five (indices 15..19) in ascending order.
    assert [d["_id"] for d in result] == [f"msg-{i:05d}" for i in range(15, 20)]
