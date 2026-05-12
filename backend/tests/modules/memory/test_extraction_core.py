"""Unit tests for the memory-extraction core.

The tests run entirely on host — no MongoDB, no Redis, no real LLM. All
collaborators are replaced with light fakes that record the calls they
receive. The point is to lock down the behaviour the live job handler
and the upcoming ChatGPT-import batch handler both depend on:

* The "no extractable content after filtering" short-circuit marks
  messages and never touches the LLM.
* The happy path persists entries inside the transaction, emits one
  ``MemoryEntryCreated`` per stored entry, and reports the right
  counters.
* Dedup against existing journal entries silently drops duplicates.
* ``ProviderUnavailableError`` propagates and the transaction rolls
  back — neither journal inserts nor the ``mark_messages_extracted``
  flip are visible afterwards.
* ``skip_budget_reserve=True`` skips the budget gate but still records
  the real spend.
* When the post-commit ``discard_oldest_uncommitted`` reports a positive
  count, a ``MemoryEntriesDiscarded`` event is published.
"""
from __future__ import annotations

import json
from typing import Any
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest

from backend.modules.memory import _extraction_core as core
from backend.modules.memory._extraction_core import (
    ExtractionResult,
    extract_and_store_messages,
)
from backend.jobs._errors import ProviderUnavailableError
from backend.modules.llm import ContentDelta, StreamDone, StreamError


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeRedis:
    """Records ``hset`` calls. Other operations are no-ops."""

    def __init__(self) -> None:
        self.hset_calls: list[tuple[str, dict[str, str]]] = []

    async def hset(self, key: str, mapping: dict[str, str]) -> int:
        self.hset_calls.append((key, dict(mapping)))
        return len(mapping)


class FakeEventBus:
    """Records every publish so tests can assert ordering and payloads."""

    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish(
        self,
        topic: str,
        event: Any,
        scope: str = "global",
        target_user_ids: list[str] | None = None,
        correlation_id: str | None = None,
        target_connection_id: str | None = None,
    ) -> None:
        self.published.append({
            "topic": str(topic),
            "event": event,
            "scope": scope,
            "target_user_ids": target_user_ids,
            "correlation_id": correlation_id,
        })


class _FakeSession:
    """Mimics enough of motor's session API for the ``async with`` blocks.

    The real code calls ``async with await client.start_session()`` and
    then ``async with session.start_transaction()``. We rollback by
    flipping ``aborted`` on exception so the fake repository can clear
    the writes it made inside the failed transaction.
    """

    def __init__(self, client: "FakeMongoClient") -> None:
        self._client = client
        self.aborted = False

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def start_transaction(self) -> "_FakeTransaction":
        return _FakeTransaction(self)


class _FakeTransaction:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> "_FakeTransaction":
        # New transaction — snapshot what the repository persisted so we
        # can roll back to it on abort.
        self._session._client.repo._snapshot()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self._session.aborted = True
            self._session._client.repo._rollback()


class FakeMongoClient:
    """The ``db.client`` surface ``extract_and_store_messages`` uses."""

    def __init__(self, repo: "FakeMemoryRepository") -> None:
        self.repo = repo

    async def start_session(self) -> _FakeSession:
        return _FakeSession(self)


class FakeDb:
    """The ``db`` argument. Only used to instantiate the repository and to
    expose ``.client`` for transaction management."""

    def __init__(self, repo: "FakeMemoryRepository") -> None:
        self._repo = repo
        self.client = FakeMongoClient(repo)


class FakeMemoryRepository:
    """In-memory stand-in for ``MemoryRepository``.

    Stores journal entries as plain dicts. Supports a tiny "snapshot /
    rollback" pair so the fake transaction can undo writes when the
    surrounding ``async with`` block exits with an exception.

    ``existing_count_uncommitted`` lets a test pretend there are N
    pre-existing uncommitted entries so the 50-cap path can be
    exercised without actually inserting 50+ rows.
    """

    def __init__(
        self,
        *,
        existing_entries: list[dict] | None = None,
        memory_body: str | None = None,
        discard_count: int = 0,
    ) -> None:
        self.existing_entries = list(existing_entries or [])
        self.memory_body = memory_body
        self.discard_count = discard_count

        self.created: list[dict] = []
        self._snapshot_created: list[dict] | None = None
        self.next_id = 1

        # Call counters for assertions.
        self.discard_calls: list[tuple[str, str, int]] = []

    # --- snapshot/rollback hooks for the fake transaction ---

    def _snapshot(self) -> None:
        self._snapshot_created = list(self.created)

    def _rollback(self) -> None:
        if self._snapshot_created is not None:
            self.created = self._snapshot_created
            self._snapshot_created = None

    # --- methods the extraction core calls ---

    async def get_current_memory_body(self, user_id: str, persona_id: str):
        if self.memory_body is None:
            return None
        return {"content": self.memory_body}

    async def list_journal_entries(self, user_id: str, persona_id: str):
        # Return existing + freshly created so dedup inside a single run
        # would still work, although in practice the function reads this
        # list once before the transaction.
        return list(self.existing_entries)

    async def create_journal_entry(
        self,
        *,
        user_id: str,
        persona_id: str,
        content: str,
        category,
        source_session_id: str,
        is_correction: bool = False,
        session=None,
        created_at=None,
    ) -> str:
        entry_id = f"entry-{self.next_id}"
        self.next_id += 1
        self.created.append({
            "_id": entry_id,
            "user_id": user_id,
            "persona_id": persona_id,
            "content": content,
            "category": category,
            "source_session_id": source_session_id,
            "is_correction": is_correction,
        })
        return entry_id

    async def discard_oldest_uncommitted(
        self, user_id: str, persona_id: str, *, max_count: int = 50,
    ) -> int:
        self.discard_calls.append((user_id, persona_id, max_count))
        return self.discard_count


# ---------------------------------------------------------------------------
# Stream-construction helpers
# ---------------------------------------------------------------------------


def _make_stream(events: list[Any]):
    """Return an async generator that yields *events* in order.

    Used to replace ``backend.modules.llm.stream_completion``.
    """

    async def _stream(*args, **kwargs):
        for ev in events:
            yield ev

    return _stream


def _make_failing_stream(message: str = "LLM must not be called"):
    """Return a stub stream that fails if it is ever iterated.

    Used in scenarios that should short-circuit before any LLM call.
    """

    async def _stream(*args, **kwargs):
        raise AssertionError(message)
        # Make the body an async generator.
        if False:  # pragma: no cover
            yield None

    return _stream


# ---------------------------------------------------------------------------
# Common test setup
# ---------------------------------------------------------------------------


@dataclass
class _Spies:
    """Container holding the patched collaborator state for assertions."""

    repo: FakeMemoryRepository
    redis: FakeRedis
    event_bus: FakeEventBus
    mark_extracted_calls: list[tuple[list[str], Any]]
    budget_reserve_calls: list[tuple[str, str]]
    record_token_calls: list[dict[str, Any]]


@pytest.fixture
def patched(monkeypatch):
    """Wire the extraction core up with the in-memory fakes.

    Returns a builder. Tests call ``patched(...)`` with the LLM stream
    events and any repo overrides; the builder returns the spy bundle
    so the test can assert against it after the function under test
    has run.
    """

    def _build(
        *,
        stream_events: list[Any] | None = None,
        repo_kwargs: dict[str, Any] | None = None,
        memory_body: str | None = None,
        existing_entries: list[dict] | None = None,
        discard_count: int = 0,
        stream_must_not_be_called: bool = False,
    ) -> tuple[_Spies, FakeDb]:
        repo_kwargs = repo_kwargs or {}
        repo = FakeMemoryRepository(
            existing_entries=existing_entries,
            memory_body=memory_body,
            discard_count=discard_count,
            **repo_kwargs,
        )
        db = FakeDb(repo)
        redis = FakeRedis()
        event_bus = FakeEventBus()
        mark_calls: list[tuple[list[str], Any]] = []
        budget_reserve_calls: list[tuple[str, str]] = []
        record_token_calls: list[dict[str, Any]] = []

        # MemoryRepository: replace with the fake at the lookup point used
        # inside the function under test.
        monkeypatch.setattr(core, "MemoryRepository", lambda _db: repo)

        # mark_messages_extracted is imported via deferred local import
        # inside the function. We patch the chat module's public symbol.
        async def _fake_mark(message_ids, *, session=None):
            mark_calls.append((list(message_ids), session))
            return len(message_ids)

        import backend.modules.chat as chat_mod
        monkeypatch.setattr(chat_mod, "mark_messages_extracted", _fake_mark)

        # stream_completion + get_model_supports_reasoning are imported
        # via deferred imports from backend.modules.llm.
        if stream_must_not_be_called:
            stream_fn = _make_failing_stream()
        else:
            stream_fn = _make_stream(stream_events or [])

        import backend.modules.llm as llm_mod
        monkeypatch.setattr(llm_mod, "stream_completion", stream_fn)

        async def _fake_supports_reasoning(user_id: str, model_unique_id: str):
            return False

        monkeypatch.setattr(
            llm_mod, "get_model_supports_reasoning", _fake_supports_reasoning,
        )

        # Settings — pretend no admin master prompt is configured.
        async def _fake_admin():
            return None

        monkeypatch.setattr(core, "get_admin_system_message", _fake_admin)

        # Budget helpers — record the calls but otherwise no-op.
        async def _fake_check(redis_arg, user_id: str, prompt_text: str) -> int:
            budget_reserve_calls.append((user_id, prompt_text))
            return 0

        async def _fake_record(
            redis_arg,
            user_id: str,
            prompt_text: str,
            output_text: str,
            input_tokens=None,
            output_tokens=None,
        ) -> None:
            record_token_calls.append({
                "user_id": user_id,
                "prompt_text": prompt_text,
                "output_text": output_text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            })

        monkeypatch.setattr(core, "check_and_reserve_budget", _fake_check)
        monkeypatch.setattr(core, "record_handler_tokens", _fake_record)

        spies = _Spies(
            repo=repo,
            redis=redis,
            event_bus=event_bus,
            mark_extracted_calls=mark_calls,
            budget_reserve_calls=budget_reserve_calls,
            record_token_calls=record_token_calls,
        )
        return spies, db

    return _build


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _llm_payload(entries: list[dict]) -> str:
    """Format a list of entry dicts as the JSON-array shape the parser expects."""
    return json.dumps(entries)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_two_entries_persisted_and_announced(self, patched) -> None:
        """Two valid JSON entries flow through the parser, get persisted
        inside the transaction, and produce one MemoryEntryCreated event
        each. The messages are marked extracted and the Redis tracking
        counter is reset. ExtractionResult carries the right counts."""
        entries = [
            {
                "content": "User enjoys fruit tea",
                "category": "preference",
                "is_correction": False,
            },
            {
                "content": "User has a sister named Anna",
                "category": "fact",
                "is_correction": False,
            },
        ]
        spies, db = patched(
            stream_events=[
                ContentDelta(delta=_llm_payload(entries)),
                StreamDone(input_tokens=200, output_tokens=50),
            ],
        )

        result = await extract_and_store_messages(
            user_id="u1",
            persona_id="p1",
            session_id="s1",
            model_unique_id="conn-1:model-a",
            messages=["I love fruit tea.", "My sister Anna sent me a photo."],
            message_ids=["m1", "m2"],
            correlation_id="corr-1",
            redis=spies.redis,
            db=db,
            event_bus=spies.event_bus,
            skip_budget_reserve=False,
        )

        assert isinstance(result, ExtractionResult)
        assert result.entries_created == 2
        assert result.messages_processed == 2
        assert result.input_tokens == 200
        assert result.output_tokens == 50

        # Both entries actually inserted by the fake repo.
        assert len(spies.repo.created) == 2
        assert spies.repo.created[0]["content"] == "User enjoys fruit tea"
        assert spies.repo.created[1]["content"] == "User has a sister named Anna"

        # mark_messages_extracted called inside the transaction with a
        # non-None session argument.
        assert len(spies.mark_extracted_calls) == 1
        ids, session = spies.mark_extracted_calls[0]
        assert ids == ["m1", "m2"]
        assert session is not None

        # Two MemoryEntryCreated events, in insertion order.
        created_topics = [
            p for p in spies.event_bus.published
            if p["topic"] == "memory.entry.created"
        ]
        assert len(created_topics) == 2
        assert created_topics[0]["event"].entry.content == "User enjoys fruit tea"
        assert created_topics[1]["event"].entry.content == "User has a sister named Anna"
        # Scope and correlation propagate.
        for ev in created_topics:
            assert ev["scope"] == "persona:p1"
            assert ev["correlation_id"] == "corr-1"
            assert ev["target_user_ids"] == ["u1"]

        # Budget reserve + record both fired exactly once.
        assert len(spies.budget_reserve_calls) == 1
        assert len(spies.record_token_calls) == 1
        # And the recorder saw the real token counts.
        assert spies.record_token_calls[0]["input_tokens"] == 200
        assert spies.record_token_calls[0]["output_tokens"] == 50

        # Redis tracking-counter reset.
        assert any(
            key == "memory:extraction:u1:p1"
            and mapping["messages_since_extraction"] == "0"
            for key, mapping in spies.redis.hset_calls
        )


class TestDedup:
    @pytest.mark.asyncio
    async def test_existing_journal_entry_filters_out_duplicate(
        self, patched,
    ) -> None:
        """When the LLM emits an entry whose normalised content matches
        an existing journal entry, the dedup pass drops it. No journal
        rows are written but the source messages are still marked so
        they don't get re-submitted by the fallback loop."""
        existing = [
            {"content": "User enjoys fruit tea"},
        ]
        entries = [
            # Same fact, different wording-but-normalised whitespace.
            {
                "content": "  USER  enjoys   fruit tea  ",
                "category": "preference",
                "is_correction": False,
            },
        ]
        spies, db = patched(
            existing_entries=existing,
            stream_events=[
                ContentDelta(delta=_llm_payload(entries)),
                StreamDone(input_tokens=10, output_tokens=5),
            ],
        )

        result = await extract_and_store_messages(
            user_id="u1",
            persona_id="p1",
            session_id="s1",
            model_unique_id="conn:model-a",
            messages=["I love fruit tea."],
            message_ids=["m1"],
            correlation_id="corr-dedup",
            redis=spies.redis,
            db=db,
            event_bus=spies.event_bus,
        )

        assert result.entries_created == 0
        # No new entries persisted.
        assert spies.repo.created == []
        # No MemoryEntryCreated events.
        created = [
            p for p in spies.event_bus.published
            if p["topic"] == "memory.entry.created"
        ]
        assert created == []
        # Message IS marked extracted even though zero entries were
        # produced — that's the documented behaviour.
        assert len(spies.mark_extracted_calls) == 1
        assert spies.mark_extracted_calls[0][0] == ["m1"]


class TestFilterEmpty:
    @pytest.mark.asyncio
    async def test_pure_code_messages_short_circuit(self, patched) -> None:
        """All-code messages strip down to empty strings. The function
        marks them extracted, bumps the Redis counter, returns zero
        entries — and never calls the LLM (stream_must_not_be_called)."""
        spies, db = patched(stream_must_not_be_called=True)

        result = await extract_and_store_messages(
            user_id="u1",
            persona_id="p1",
            session_id="s1",
            model_unique_id="conn:model-a",
            messages=[
                "```python\nprint('hello')\n```",
                "```\nlog line stuff\n```",
            ],
            message_ids=["m1", "m2"],
            correlation_id="corr-short",
            redis=spies.redis,
            db=db,
            event_bus=spies.event_bus,
        )

        assert result == ExtractionResult(
            entries_created=0,
            messages_processed=2,
            input_tokens=None,
            output_tokens=None,
        )
        # Messages marked extracted (without a session — the fast path
        # does not run inside a transaction).
        assert len(spies.mark_extracted_calls) == 1
        ids, session = spies.mark_extracted_calls[0]
        assert ids == ["m1", "m2"]
        assert session is None
        # Tracking-counter reset fired.
        assert spies.redis.hset_calls and (
            spies.redis.hset_calls[0][0] == "memory:extraction:u1:p1"
        )
        # Budget reserve + record never called (no LLM round-trip).
        assert spies.budget_reserve_calls == []
        assert spies.record_token_calls == []
        # No MemoryEntryCreated events emitted.
        assert [
            p for p in spies.event_bus.published
            if p["topic"] == "memory.entry.created"
        ] == []


class TestProviderUnavailable:
    @pytest.mark.asyncio
    async def test_stream_error_raises_and_rolls_back(self, patched) -> None:
        """A StreamError(provider_unavailable) is converted into a
        ProviderUnavailableError. Because that fires before the Mongo
        transaction even opens, no journal entries are created and the
        messages are NOT marked extracted."""
        spies, db = patched(
            stream_events=[
                StreamError(
                    error_code="provider_unavailable",
                    message="connection refused",
                ),
                # Add a Done after the error in case the consumer keeps
                # iterating; the function should never get here.
                StreamDone(input_tokens=0, output_tokens=0),
            ],
        )

        with pytest.raises(ProviderUnavailableError):
            await extract_and_store_messages(
                user_id="u1",
                persona_id="p1",
                session_id="s1",
                model_unique_id="conn:model-a",
                messages=["Hi there."],
                message_ids=["m1"],
                correlation_id="corr-provider",
                redis=spies.redis,
                db=db,
                event_bus=spies.event_bus,
            )

        # No writes happened.
        assert spies.repo.created == []
        # No mark_messages_extracted call.
        assert spies.mark_extracted_calls == []
        # No entry-created events leaked.
        assert [
            p for p in spies.event_bus.published
            if p["topic"] == "memory.entry.created"
        ] == []


class TestSkipBudgetReserve:
    @pytest.mark.asyncio
    async def test_skip_reserve_bypasses_gate_but_records_spend(
        self, patched,
    ) -> None:
        """``skip_budget_reserve=True`` must skip the pre-call gate but
        still record the post-call spend so the daily usage log stays
        honest. Used by the ChatGPT-import batch handler when the user
        opts into 'force budget'."""
        entries = [
            {
                "content": "User likes mountain hiking",
                "category": "preference",
                "is_correction": False,
            },
        ]
        spies, db = patched(
            stream_events=[
                ContentDelta(delta=_llm_payload(entries)),
                StreamDone(input_tokens=12, output_tokens=8),
            ],
        )

        result = await extract_and_store_messages(
            user_id="u1",
            persona_id="p1",
            session_id="s1",
            model_unique_id="conn:model-a",
            messages=["I love hiking."],
            message_ids=["m1"],
            correlation_id="corr-skip",
            redis=spies.redis,
            db=db,
            event_bus=spies.event_bus,
            skip_budget_reserve=True,
        )

        assert result.entries_created == 1
        # No budget gate.
        assert spies.budget_reserve_calls == []
        # But the recorder ran and saw the real counts.
        assert len(spies.record_token_calls) == 1
        assert spies.record_token_calls[0]["input_tokens"] == 12
        assert spies.record_token_calls[0]["output_tokens"] == 8


class TestCapEnforcement:
    @pytest.mark.asyncio
    async def test_positive_discard_count_publishes_event(self, patched) -> None:
        """When ``discard_oldest_uncommitted`` reports it removed N
        entries to respect the 50-cap, a MemoryEntriesDiscarded event
        is published with that count."""
        entries = [
            {
                "content": "User likes cats",
                "category": "preference",
                "is_correction": False,
            },
        ]
        spies, db = patched(
            stream_events=[
                ContentDelta(delta=_llm_payload(entries)),
                StreamDone(input_tokens=10, output_tokens=4),
            ],
            discard_count=3,
        )

        await extract_and_store_messages(
            user_id="u1",
            persona_id="p1",
            session_id="s1",
            model_unique_id="conn:model-a",
            messages=["Cats are great."],
            message_ids=["m1"],
            correlation_id="corr-cap",
            redis=spies.redis,
            db=db,
            event_bus=spies.event_bus,
        )

        # discard called with the 50 cap.
        assert spies.repo.discard_calls == [("u1", "p1", 50)]
        # And the event fired with the right count.
        discarded = [
            p for p in spies.event_bus.published
            if p["topic"] == "memory.entries.discarded"
        ]
        assert len(discarded) == 1
        assert discarded[0]["event"].discarded_count == 3
        assert discarded[0]["scope"] == "persona:p1"
        assert discarded[0]["correlation_id"] == "corr-cap"

    @pytest.mark.asyncio
    async def test_zero_discard_count_publishes_nothing(self, patched) -> None:
        entries = [
            {
                "content": "User likes dogs",
                "category": "preference",
                "is_correction": False,
            },
        ]
        spies, db = patched(
            stream_events=[
                ContentDelta(delta=_llm_payload(entries)),
                StreamDone(input_tokens=10, output_tokens=4),
            ],
            discard_count=0,
        )

        await extract_and_store_messages(
            user_id="u1",
            persona_id="p1",
            session_id="s1",
            model_unique_id="conn:model-a",
            messages=["Dogs are great."],
            message_ids=["m1"],
            correlation_id="corr-no-cap",
            redis=spies.redis,
            db=db,
            event_bus=spies.event_bus,
        )

        discarded = [
            p for p in spies.event_bus.published
            if p["topic"] == "memory.entries.discarded"
        ]
        assert discarded == []
