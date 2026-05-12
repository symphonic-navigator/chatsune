"""Tests for the ChatGPT-import memory-batch job handler.

Host-runnable: no Mongo, no Redis, no real LLM. The repository is
stubbed by patching the module symbol, the chat module's public API
functions are patched, and ``extract_and_store_messages`` is replaced
by a recording stub so we can assert call ordering, payload contents,
and failure-path behaviour without spinning up infrastructure.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from backend.jobs._errors import ProviderUnavailableError, UnrecoverableJobError
from backend.jobs._models import JobEntry, JobType
import backend.jobs.handlers._chatgpt_import_memory_batch as batch_handler
from backend.modules.memory._extraction_core import ExtractionResult


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeRedis:
    """Records slot operations.

    ``set(nx=True, ex=...)`` returns ``True`` on first call (slot
    free) and ``False`` thereafter. ``delete`` and ``expire`` track
    their invocations so the test can assert TTL transitions.
    """

    def __init__(self, *, slot_acquirable: bool = True) -> None:
        self.acquirable = slot_acquirable
        self.holders: set[str] = set()
        self.expire_calls: list[tuple[str, int]] = []
        self.delete_calls: list[str] = []
        self.set_calls: list[tuple[str, dict[str, Any]]] = []

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        self.set_calls.append((key, {"value": value, "nx": nx, "ex": ex}))
        if nx:
            if key in self.holders or not self.acquirable:
                return None
            self.holders.add(key)
            return True
        self.holders.add(key)
        return True

    async def expire(self, key: str, ttl: int) -> bool:
        self.expire_calls.append((key, ttl))
        return True

    async def delete(self, key: str) -> int:
        self.delete_calls.append(key)
        self.holders.discard(key)
        return 1


class FakeEventBus:
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
            "target_user_ids": list(target_user_ids or []),
            "correlation_id": correlation_id,
        })


class FakeBatchRepo:
    """In-memory stand-in for ``ChatGptImportMemoryBatchRepository``."""

    def __init__(self, doc: dict | None) -> None:
        self.doc = dict(doc) if doc else None
        self.mark_paused_calls: list[dict[str, Any]] = []
        self.mark_done_calls: list[tuple[str, str]] = []
        self.entries_added: list[int] = []

    async def get(self, import_id: str, persona_id: str) -> dict | None:
        if self.doc is None:
            return None
        return dict(self.doc)

    async def mark_paused(self, **kwargs) -> dict | None:
        self.mark_paused_calls.append(dict(kwargs))
        if self.doc is None:
            return None
        self.doc["state"] = "paused"
        self.doc["paused_at"] = {
            "session_index": kwargs["session_index"],
            "session_id": kwargs["session_id"],
            "reason": kwargs["reason"],
            "user_message": kwargs["user_message"],
            "detail": kwargs.get("detail"),
            "at": datetime.now(UTC),
        }
        return dict(self.doc)

    async def mark_done(self, import_id: str, persona_id: str) -> dict | None:
        self.mark_done_calls.append((import_id, persona_id))
        if self.doc is None:
            return None
        self.doc["state"] = "done"
        self.doc["paused_at"] = None
        return dict(self.doc)

    async def add_entries_created(
        self, import_id: str, persona_id: str, count: int,
    ) -> None:
        self.entries_added.append(count)
        if self.doc is not None:
            self.doc["total_entries_created"] = (
                int(self.doc.get("total_entries_created", 0)) + count
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(
    *,
    import_id: str = "imp1",
    persona_id: str = "p1",
    force_budget: bool = False,
    user_id: str = "u1",
) -> JobEntry:
    return JobEntry(
        id="j1",
        job_type=JobType.CHATGPT_IMPORT_MEMORY_BATCH,
        user_id=user_id,
        model_unique_id="conn:m",
        payload={
            "import_id": import_id,
            "persona_id": persona_id,
            "force_budget": force_budget,
        },
        correlation_id="corr-batch",
        created_at=datetime.now(UTC),
    )


def _batch_doc(
    *,
    state: str = "running",
    session_ids: list[str] | None = None,
    target_count: int = 3,
    total_entries_created: int = 0,
) -> dict:
    return {
        "_id": "imp1:p1",
        "import_id": "imp1",
        "persona_id": "p1",
        "user_id": "u1",
        "model_unique_id": "conn:m",
        "state": state,
        "target_count": target_count,
        "conversations_imported": target_count,
        "permanent_failures": 0,
        "session_ids": list(session_ids or ["s-old", "s-mid", "s-new"]),
        "paused_at": None,
        "total_entries_created": total_entries_created,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


@pytest.fixture
def patched(monkeypatch):
    """Wire the handler with in-memory fakes for every collaborator.

    The returned builder takes per-test overrides for:

    - ``batch_doc``: the initial repository state (or None for missing).
    - ``unextracted_by_session``: maps session_id -> list of message-id
      lists handed out in successive ``list_unextracted_user_messages``
      calls. An empty list ends the inner loop for that session.
    - ``extract_side_effects``: maps session_id -> list of
      side-effects per call (an ExtractionResult or an Exception). Items
      are popped left-to-right.
    - ``deleted_sessions``: set of session_ids that
      ``get_session_summaries`` will omit (modelling soft-deletes).
    - ``slot_acquirable``: forces the Redis slot to be busy.
    """

    def _build(
        *,
        batch_doc: dict | None,
        unextracted_by_session: dict[str, list[list[str]]] | None = None,
        extract_side_effects: dict[str, list[Any]] | None = None,
        deleted_sessions: set[str] | None = None,
        slot_acquirable: bool = True,
    ):
        repo = FakeBatchRepo(batch_doc)
        monkeypatch.setattr(
            batch_handler, "ChatGptImportMemoryBatchRepository", lambda _db: repo,
        )

        # get_db / get_session_summaries / list_unextracted_messages_for_session
        # are looked up via deferred imports inside the handler. Patch the
        # public surface of the chat module at the names the handler binds
        # to after its import.
        deleted = set(deleted_sessions or ())
        session_ids = list((batch_doc or {}).get("session_ids") or [])

        async def _fake_summaries(session_ids_in: list[str], user_id: str):
            return {
                sid: {"title": f"title-{sid}", "persona_id": "p1"}
                for sid in session_ids_in
                if sid not in deleted
            }

        unextracted_state = {
            sid: list(chunks) for sid, chunks in (unextracted_by_session or {}).items()
        }

        async def _fake_list_unextracted(session_id: str, limit: int = 20):
            chunks = unextracted_state.get(session_id) or []
            if not chunks:
                return []
            ids = chunks.pop(0)
            return [{"_id": mid, "content": f"text-{mid}"} for mid in ids]

        import backend.modules.chat as chat_mod
        monkeypatch.setattr(chat_mod, "get_session_summaries", _fake_summaries)
        monkeypatch.setattr(
            chat_mod, "list_unextracted_messages_for_session", _fake_list_unextracted,
        )

        # extract_and_store_messages: capture every call and pop the
        # configured side-effect.
        extract_calls: list[dict[str, Any]] = []
        side_state = {
            sid: list(effects) for sid, effects in (extract_side_effects or {}).items()
        }

        async def _fake_extract(**kwargs):
            extract_calls.append(dict(kwargs))
            sid = kwargs["session_id"]
            effects = side_state.get(sid) or []
            if not effects:
                # Default: produce one entry for the messages we got.
                return ExtractionResult(
                    entries_created=len(kwargs["message_ids"]),
                    messages_processed=len(kwargs["message_ids"]),
                    input_tokens=10,
                    output_tokens=4,
                )
            effect = effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
            return effect

        import backend.modules.memory as memory_mod
        monkeypatch.setattr(memory_mod, "extract_and_store_messages", _fake_extract)

        # get_db is called by the handler; the value is only passed to
        # extract_and_store_messages (which is itself patched), so any
        # sentinel works.
        monkeypatch.setattr(batch_handler, "get_db", lambda: object())

        return {
            "repo": repo,
            "extract_calls": extract_calls,
            "session_ids": session_ids,
        }

    return _build


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_three_sessions_done_in_order(self, patched):
        """All three imported sessions extract successfully — the handler
        flips state to done and publishes ``ChatGptImportMemoryBatchDoneEvent``.
        The order of calls matches the chronological session list."""
        ctx = patched(
            batch_doc=_batch_doc(),
            unextracted_by_session={
                "s-old": [["m1", "m2"], []],
                "s-mid": [["m3"], []],
                "s-new": [["m4"], []],
            },
        )
        job = _make_job()
        redis = FakeRedis()
        event_bus = FakeEventBus()

        await batch_handler.handle_chatgpt_import_memory_batch(
            job, config=None, redis=redis, event_bus=event_bus,  # type: ignore[arg-type]
        )

        # Extraction was called once per session, in order.
        order = [c["session_id"] for c in ctx["extract_calls"]]
        assert order == ["s-old", "s-mid", "s-new"]

        # Terminal state is done.
        assert ctx["repo"].mark_done_calls == [("imp1", "p1")]

        # Done event was published on both scopes.
        done_topics = [
            p for p in event_bus.published
            if p["topic"] == "chatgpt_import.memory.done"
        ]
        scopes = sorted(p["scope"] for p in done_topics)
        assert scopes == ["chatgpt_import:imp1", "persona:p1"]

        # Slot was released (delete called) at the end.
        assert "jobs:inflight:memory_extraction:u1:p1" in redis.delete_calls


class TestForceBudget:
    @pytest.mark.asyncio
    async def test_force_budget_propagates_to_extract(self, patched):
        ctx = patched(
            batch_doc=_batch_doc(session_ids=["s1"]),
            unextracted_by_session={"s1": [["m1"], []]},
        )
        job = _make_job(force_budget=True)
        await batch_handler.handle_chatgpt_import_memory_batch(
            job, config=None, redis=FakeRedis(), event_bus=FakeEventBus(),  # type: ignore[arg-type]
        )
        assert ctx["extract_calls"][0]["skip_budget_reserve"] is True


class TestSessionDeleted:
    @pytest.mark.asyncio
    async def test_deleted_session_skipped_silently(self, patched):
        """A session that's been soft-deleted between submit and run is
        absent from ``get_session_summaries``. The handler skips it and
        moves on without raising."""
        ctx = patched(
            batch_doc=_batch_doc(session_ids=["s1", "s2", "s3"]),
            unextracted_by_session={
                "s1": [["m1"], []],
                # s2 is deleted; never queried for unextracted.
                "s3": [["m3"], []],
            },
            deleted_sessions={"s2"},
        )
        await batch_handler.handle_chatgpt_import_memory_batch(
            _make_job(), config=None, redis=FakeRedis(), event_bus=FakeEventBus(),  # type: ignore[arg-type]
        )
        # Only s1 and s3 went through extraction.
        assert [c["session_id"] for c in ctx["extract_calls"]] == ["s1", "s3"]
        # And we still completed.
        assert ctx["repo"].mark_done_calls == [("imp1", "p1")]


class TestProviderUnavailable:
    @pytest.mark.asyncio
    async def test_pauses_with_provider_reason_and_extends_slot(self, patched):
        """A ``ProviderUnavailableError`` mid-batch transitions to paused,
        records the failing session index, and bumps the slot TTL to the
        7-day hold."""
        ctx = patched(
            batch_doc=_batch_doc(session_ids=["s1", "s2", "s3"]),
            unextracted_by_session={
                "s1": [["m1"], []],
                "s2": [["m2"]],  # never drained
                "s3": [["m3"], []],
            },
            extract_side_effects={
                "s2": [ProviderUnavailableError("connection refused")],
            },
        )
        redis = FakeRedis()
        event_bus = FakeEventBus()
        await batch_handler.handle_chatgpt_import_memory_batch(
            _make_job(), config=None, redis=redis, event_bus=event_bus,  # type: ignore[arg-type]
        )
        # Paused at session index 2.
        assert len(ctx["repo"].mark_paused_calls) == 1
        call = ctx["repo"].mark_paused_calls[0]
        assert call["session_index"] == 2
        assert call["session_id"] == "s2"
        assert call["reason"] == "provider_unavailable"
        # No mark_done.
        assert ctx["repo"].mark_done_calls == []
        # Slot's TTL was extended to the 7-day hold.
        assert any(
            ttl == 7 * 24 * 3600 for _key, ttl in redis.expire_calls
        )
        # Paused event was published on both scopes.
        paused_topics = [
            p for p in event_bus.published
            if p["topic"] == "chatgpt_import.memory.paused"
        ]
        scopes = sorted(p["scope"] for p in paused_topics)
        assert scopes == ["chatgpt_import:imp1", "persona:p1"]


class TestBudgetExhausted:
    @pytest.mark.asyncio
    async def test_unrecoverable_error_is_budget_pause(self, patched):
        """``UnrecoverableJobError`` is the exception
        ``check_and_reserve_budget`` raises when the daily cap is hit.
        The handler treats it as a budget pause so the UI can offer the
        force-budget Resume variant."""
        ctx = patched(
            batch_doc=_batch_doc(session_ids=["s1"]),
            unextracted_by_session={"s1": [["m1"]]},
            extract_side_effects={
                "s1": [UnrecoverableJobError("Daily budget exhausted")],
            },
        )
        await batch_handler.handle_chatgpt_import_memory_batch(
            _make_job(), config=None, redis=FakeRedis(), event_bus=FakeEventBus(),  # type: ignore[arg-type]
        )
        call = ctx["repo"].mark_paused_calls[0]
        assert call["reason"] == "budget_exhausted"


class TestResumeIdempotency:
    @pytest.mark.asyncio
    async def test_already_extracted_sessions_skip(self, patched):
        """On Resume, sessions whose messages already carry
        ``extracted_at`` (modelled as empty ``list_unextracted_*``)
        skip past the inner loop. Only sessions with pending work
        invoke ``extract_and_store_messages``."""
        ctx = patched(
            batch_doc=_batch_doc(session_ids=["s1", "s2", "s3"]),
            unextracted_by_session={
                # s1 + s2 already drained in a previous run.
                "s1": [[]],
                "s2": [[]],
                # s3 still has work to do.
                "s3": [["m3"], []],
            },
        )
        await batch_handler.handle_chatgpt_import_memory_batch(
            _make_job(), config=None, redis=FakeRedis(), event_bus=FakeEventBus(),  # type: ignore[arg-type]
        )
        # Only s3's call hit the extract function.
        assert [c["session_id"] for c in ctx["extract_calls"]] == ["s3"]
        assert ctx["repo"].mark_done_calls == [("imp1", "p1")]


class TestSlotBusy:
    @pytest.mark.asyncio
    async def test_slot_busy_pauses_with_other_reason(self, patched):
        """If the per-persona memory-extraction slot is already held
        (e.g. by a still-in-flight live extraction), the batch pauses
        with reason="other" so the user can hit Resume in a moment."""
        ctx = patched(
            batch_doc=_batch_doc(session_ids=["s1"]),
            unextracted_by_session={"s1": [["m1"], []]},
            slot_acquirable=False,
        )
        redis = FakeRedis(slot_acquirable=False)
        await batch_handler.handle_chatgpt_import_memory_batch(
            _make_job(), config=None, redis=redis, event_bus=FakeEventBus(),  # type: ignore[arg-type]
        )
        call = ctx["repo"].mark_paused_calls[0]
        assert call["reason"] == "other"
        # No extract calls happened.
        assert ctx["extract_calls"] == []


class TestMissingBatch:
    @pytest.mark.asyncio
    async def test_missing_doc_returns_quietly(self, patched):
        patched(batch_doc=None)
        # Should not raise.
        await batch_handler.handle_chatgpt_import_memory_batch(
            _make_job(), config=None, redis=FakeRedis(), event_bus=FakeEventBus(),  # type: ignore[arg-type]
        )

    @pytest.mark.asyncio
    async def test_doc_not_in_running_state(self, patched):
        """If the row is e.g. discarded (race), the handler logs and
        returns without modifying state."""
        ctx = patched(batch_doc=_batch_doc(state="discarded"))
        await batch_handler.handle_chatgpt_import_memory_batch(
            _make_job(), config=None, redis=FakeRedis(), event_bus=FakeEventBus(),  # type: ignore[arg-type]
        )
        assert ctx["repo"].mark_done_calls == []
        assert ctx["repo"].mark_paused_calls == []
