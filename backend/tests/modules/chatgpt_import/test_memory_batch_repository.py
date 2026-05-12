"""Tests for ``ChatGptImportMemoryBatchRepository``.

These run entirely on host — there is no Mongo connection. The
repository is exercised against a tiny in-memory fake that implements
enough of the motor / pymongo surface (specifically
``find_one_and_update`` with the ``state`` filter and
``ReturnDocument.AFTER`` semantics) to make the atomicity assertions
meaningful.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pymongo import ReturnDocument

from backend.modules.chatgpt_import._memory_batch_repository import (
    ChatGptImportMemoryBatchRepository,
)


# ---------------------------------------------------------------------------
# In-memory fake of the motor collection surface used by the repository.
# ---------------------------------------------------------------------------


def _matches(doc: dict, filter_: dict) -> bool:
    """Lightweight Mongo-style filter matcher.

    Supports plain equality and ``{"$in": [...]}`` — the only operators
    the repository uses.
    """
    for key, expected in filter_.items():
        actual = doc.get(key)
        if isinstance(expected, dict) and "$in" in expected:
            if actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


def _apply(doc: dict, update: dict, *, is_insert: bool = False) -> dict:
    """Apply ``$set``, ``$setOnInsert``, ``$inc`` operators to ``doc``.

    ``$setOnInsert`` mirrors MongoDB semantics: only applied when the
    operation is an actual insert (upsert that didn't match). On a
    regular update the operator is a no-op.
    """
    out = dict(doc)
    for op, fields in update.items():
        if op == "$set":
            out.update(fields)
        elif op == "$setOnInsert":
            if is_insert:
                out.update(fields)
        elif op == "$inc":
            for k, v in fields.items():
                out[k] = int(out.get(k, 0)) + int(v)
        else:
            raise NotImplementedError(f"Unhandled operator {op}")
    return out


class FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    async def to_list(self, length: int | None = None) -> list[dict]:
        if length is None:
            return list(self._docs)
        return list(self._docs[:length])


class FakeCollection:
    """Minimal stand-in for an ``AsyncIOMotorCollection``."""

    def __init__(self) -> None:
        self._docs: dict[str, dict] = {}
        self.index_calls: list[Any] = []

    async def find_one_and_update(
        self,
        filter_: dict,
        update: dict,
        *,
        upsert: bool = False,
        return_document=ReturnDocument.BEFORE,
    ) -> dict | None:
        doc_id = filter_.get("_id")
        existing = self._docs.get(doc_id) if doc_id else None
        if existing is not None and not _matches(existing, filter_):
            existing = None
        if existing is None:
            if not upsert:
                return None
            new = _apply({"_id": doc_id} if doc_id else {}, update, is_insert=True)
            self._docs[new["_id"]] = new
            return deepcopy(new) if return_document == ReturnDocument.AFTER else None
        updated = _apply(existing, update, is_insert=False)
        self._docs[updated["_id"]] = updated
        if return_document == ReturnDocument.AFTER:
            return deepcopy(updated)
        return deepcopy(existing)

    async def update_one(self, filter_: dict, update: dict) -> Any:
        doc_id = filter_.get("_id")
        existing = self._docs.get(doc_id) if doc_id else None
        if existing is None or not _matches(existing, filter_):
            return None
        self._docs[doc_id] = _apply(existing, update)
        return None

    async def find_one(self, filter_: dict) -> dict | None:
        for doc in self._docs.values():
            if _matches(doc, filter_):
                return deepcopy(doc)
        return None

    async def delete_many(self, filter_: dict) -> Any:
        matching_ids = [k for k, doc in self._docs.items() if _matches(doc, filter_)]
        for k in matching_ids:
            del self._docs[k]

        class _Result:
            deleted_count = len(matching_ids)
        return _Result()

    def find(self, filter_: dict, projection: dict | None = None) -> FakeCursor:
        out = [deepcopy(doc) for doc in self._docs.values() if _matches(doc, filter_)]
        return FakeCursor(out)

    async def create_index(self, keys, **kwargs) -> str:
        self.index_calls.append((tuple(keys), kwargs))
        return "ix"


class FakeDb:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_and_coll() -> tuple[ChatGptImportMemoryBatchRepository, FakeCollection]:
    db = FakeDb()
    repo = ChatGptImportMemoryBatchRepository(db)  # type: ignore[arg-type]
    coll = db["chatgpt_import_memory_batches"]
    return repo, coll


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEnsureBatch:
    @pytest.mark.asyncio
    async def test_insert_creates_pending_row(self, repo_and_coll):
        repo, coll = repo_and_coll
        doc = await repo.ensure_batch(
            import_id="imp1",
            persona_id="p1",
            user_id="u1",
            model_unique_id="conn:m",
            target_count=3,
        )
        assert doc["_id"] == "imp1:p1"
        assert doc["state"] == "pending"
        assert doc["target_count"] == 3
        assert doc["conversations_imported"] == 0
        assert doc["permanent_failures"] == 0
        assert doc["total_entries_created"] == 0
        assert doc["session_ids"] == []
        assert doc["paused_at"] is None

    @pytest.mark.asyncio
    async def test_second_call_is_no_op(self, repo_and_coll):
        """A second ensure_batch with different target_count must not
        overwrite the original: ``$setOnInsert`` ignores existing docs."""
        repo, _coll = repo_and_coll
        first = await repo.ensure_batch(
            import_id="imp1",
            persona_id="p1",
            user_id="u1",
            model_unique_id="conn:m",
            target_count=3,
        )
        second = await repo.ensure_batch(
            import_id="imp1",
            persona_id="p1",
            user_id="u1",
            model_unique_id="conn:m",
            target_count=999,  # would be wrong if it overwrote
        )
        assert second["target_count"] == first["target_count"] == 3


class TestClaimRunning:
    @pytest.mark.asyncio
    async def test_first_claim_wins(self, repo_and_coll):
        """Two callers race; only the first observes state=pending and
        gets a row back. The second sees state=running and gets None."""
        repo, _coll = repo_and_coll
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=2,
        )
        first = await repo.claim_running(
            import_id="imp1", persona_id="p1",
            session_ids=["s1", "s2"],
        )
        second = await repo.claim_running(
            import_id="imp1", persona_id="p1",
            session_ids=["s1", "s2"],
        )
        assert first is not None
        assert first["state"] == "running"
        assert first["session_ids"] == ["s1", "s2"]
        assert second is None

    @pytest.mark.asyncio
    async def test_claim_missing_row(self, repo_and_coll):
        repo, _coll = repo_and_coll
        result = await repo.claim_running(
            import_id="imp1", persona_id="p1", session_ids=[],
        )
        assert result is None


class TestCounters:
    @pytest.mark.asyncio
    async def test_increment_imported_until_target(self, repo_and_coll):
        """Manually drive imported up to ``target_count - failures``; the
        last increment satisfies the trigger condition checked by the
        per-conversation handler."""
        repo, _coll = repo_and_coll
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=3,
        )
        d1 = await repo.increment_imported("imp1", "p1")
        d2 = await repo.increment_imported("imp1", "p1")
        assert d1["conversations_imported"] == 1
        assert d2["conversations_imported"] == 2
        # Trigger check would still fail (1+0 != 3, 2+0 != 3)
        assert d1["conversations_imported"] + d1["permanent_failures"] != d1["target_count"]
        assert d2["conversations_imported"] + d2["permanent_failures"] != d2["target_count"]
        d3 = await repo.increment_imported("imp1", "p1")
        # Trigger fires now: 3 + 0 == 3
        assert d3["conversations_imported"] + d3["permanent_failures"] == d3["target_count"]

    @pytest.mark.asyncio
    async def test_increment_failures_then_trigger(self, repo_and_coll):
        repo, _coll = repo_and_coll
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=3,
        )
        await repo.increment_failures("imp1", "p1")
        d = await repo.increment_imported("imp1", "p1")
        # 1 imported + 1 failed == 2 ≠ 3 → no trigger
        assert d["conversations_imported"] + d["permanent_failures"] == 2
        d = await repo.increment_imported("imp1", "p1")
        # 2 imported + 1 failed == 3 == target → trigger
        assert d["conversations_imported"] + d["permanent_failures"] == d["target_count"]


class TestMarkPaused:
    @pytest.mark.asyncio
    async def test_paused_sets_state_and_paused_at(self, repo_and_coll):
        repo, _coll = repo_and_coll
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=1,
        )
        await repo.claim_running(
            import_id="imp1", persona_id="p1", session_ids=["s1"],
        )
        paused = await repo.mark_paused(
            import_id="imp1", persona_id="p1",
            session_index=1, session_id="s1",
            reason="provider_unavailable",
            user_message="Provider not reachable. Try Resume later.",
            detail="connection refused",
        )
        assert paused["state"] == "paused"
        assert paused["paused_at"]["reason"] == "provider_unavailable"
        assert paused["paused_at"]["session_id"] == "s1"
        assert paused["paused_at"]["detail"] == "connection refused"


class TestMarkDoneAndDiscarded:
    @pytest.mark.asyncio
    async def test_done_clears_paused_at(self, repo_and_coll):
        repo, _coll = repo_and_coll
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=1,
        )
        await repo.claim_running(
            import_id="imp1", persona_id="p1", session_ids=["s1"],
        )
        await repo.mark_paused(
            import_id="imp1", persona_id="p1",
            session_index=1, session_id="s1",
            reason="other", user_message="x",
        )
        done = await repo.mark_done("imp1", "p1")
        assert done["state"] == "done"
        assert done["paused_at"] is None

    @pytest.mark.asyncio
    async def test_discarded_only_if_paused(self, repo_and_coll):
        """``only_if_paused=True`` is the path used by the REST handler.
        A row in ``running`` state must not be discarded."""
        repo, _coll = repo_and_coll
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=1,
        )
        await repo.claim_running(
            import_id="imp1", persona_id="p1", session_ids=["s1"],
        )
        result = await repo.mark_discarded(
            import_id="imp1", persona_id="p1", only_if_paused=True,
        )
        assert result is None  # not paused
        # Now flip to paused and try again
        await repo.mark_paused(
            import_id="imp1", persona_id="p1",
            session_index=1, session_id="s1",
            reason="other", user_message="x",
        )
        result = await repo.mark_discarded(
            import_id="imp1", persona_id="p1", only_if_paused=True,
        )
        assert result is not None
        assert result["state"] == "discarded"
        assert result["paused_at"] is None


class TestListPendingForUser:
    @pytest.mark.asyncio
    async def test_returns_running_and_paused_only(self, repo_and_coll):
        repo, _coll = repo_and_coll
        # Two batches for u1, one for u2; mix of states.
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=1,
        )
        await repo.ensure_batch(
            import_id="imp2", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=1,
        )
        await repo.ensure_batch(
            import_id="imp3", persona_id="p1", user_id="u2",
            model_unique_id="conn:m", target_count=1,
        )
        await repo.claim_running(
            import_id="imp1", persona_id="p1", session_ids=["a"],
        )
        await repo.claim_running(
            import_id="imp2", persona_id="p1", session_ids=["b"],
        )
        await repo.mark_paused(
            import_id="imp2", persona_id="p1",
            session_index=1, session_id="b",
            reason="other", user_message="x",
        )
        await repo.claim_running(
            import_id="imp3", persona_id="p1", session_ids=["c"],
        )
        await repo.mark_done("imp3", "p1")

        active = await repo.list_pending_for_user("u1")
        ids = sorted(d["_id"] for d in active)
        # imp1 running, imp2 paused — both included; imp3 done is not.
        assert ids == ["imp1:p1", "imp2:p1"]


class TestClaimResume:
    @pytest.mark.asyncio
    async def test_resume_only_from_paused(self, repo_and_coll):
        repo, _coll = repo_and_coll
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=1,
        )
        # Cannot resume from pending.
        assert await repo.claim_resume(import_id="imp1", persona_id="p1") is None
        await repo.claim_running(
            import_id="imp1", persona_id="p1", session_ids=["s1"],
        )
        # Cannot resume from running.
        assert await repo.claim_resume(import_id="imp1", persona_id="p1") is None
        # Pause then resume succeeds.
        await repo.mark_paused(
            import_id="imp1", persona_id="p1",
            session_index=1, session_id="s1",
            reason="other", user_message="x",
        )
        resumed = await repo.claim_resume(import_id="imp1", persona_id="p1")
        assert resumed is not None
        assert resumed["state"] == "running"
        assert resumed["paused_at"] is None


class TestAddEntriesCreated:
    @pytest.mark.asyncio
    async def test_adds_to_total(self, repo_and_coll):
        repo, _coll = repo_and_coll
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=1,
        )
        await repo.add_entries_created("imp1", "p1", 3)
        await repo.add_entries_created("imp1", "p1", 2)
        doc = await repo.get("imp1", "p1")
        assert doc["total_entries_created"] == 5

    @pytest.mark.asyncio
    async def test_zero_is_noop(self, repo_and_coll):
        repo, _coll = repo_and_coll
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=1,
        )
        await repo.add_entries_created("imp1", "p1", 0)
        doc = await repo.get("imp1", "p1")
        assert doc["total_entries_created"] == 0


class TestStartNewAction:
    @pytest.mark.asyncio
    async def test_inserts_when_no_doc_exists(self, repo_and_coll):
        repo, _coll = repo_and_coll
        doc = await repo.start_new_action(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=3,
        )
        assert doc["state"] == "pending"
        assert doc["target_count"] == 3
        assert doc["conversations_imported"] == 0
        assert doc["permanent_failures"] == 0

    @pytest.mark.asyncio
    async def test_resets_done_batch_for_new_action(self, repo_and_coll):
        repo, _coll = repo_and_coll
        # Simulate a completed first action.
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m1", target_count=2,
        )
        await repo.increment_imported("imp1", "p1")
        await repo.increment_imported("imp1", "p1")
        await repo.claim_running(
            import_id="imp1", persona_id="p1", session_ids=["s1", "s2"],
        )
        await repo.add_entries_created("imp1", "p1", 5)
        await repo.mark_done("imp1", "p1")

        # Now the user starts a fresh action — different model, different size.
        doc = await repo.start_new_action(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m2", target_count=4,
        )
        assert doc["state"] == "pending"
        assert doc["target_count"] == 4
        assert doc["conversations_imported"] == 0
        assert doc["permanent_failures"] == 0
        assert doc["session_ids"] == []
        assert doc["paused_at"] is None
        assert doc["total_entries_created"] == 0
        assert doc["model_unique_id"] == "conn:m2"

    @pytest.mark.asyncio
    async def test_resets_discarded_batch(self, repo_and_coll):
        repo, _coll = repo_and_coll
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=1,
        )
        await repo.mark_discarded(import_id="imp1", persona_id="p1")
        doc = await repo.start_new_action(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=2,
        )
        assert doc["state"] == "pending"
        assert doc["target_count"] == 2

    @pytest.mark.asyncio
    async def test_raises_when_pending_in_progress(self, repo_and_coll):
        repo, _coll = repo_and_coll
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=2,
        )
        from backend.modules.chatgpt_import._memory_batch_repository import (
            BatchInProgressError,
        )
        with pytest.raises(BatchInProgressError) as exc_info:
            await repo.start_new_action(
                import_id="imp1", persona_id="p1", user_id="u1",
                model_unique_id="conn:m", target_count=2,
            )
        assert exc_info.value.current_state == "pending"

    @pytest.mark.asyncio
    async def test_raises_when_running_in_progress(self, repo_and_coll):
        repo, _coll = repo_and_coll
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=1,
        )
        await repo.claim_running(
            import_id="imp1", persona_id="p1", session_ids=["s1"],
        )
        from backend.modules.chatgpt_import._memory_batch_repository import (
            BatchInProgressError,
        )
        with pytest.raises(BatchInProgressError):
            await repo.start_new_action(
                import_id="imp1", persona_id="p1", user_id="u1",
                model_unique_id="conn:m", target_count=2,
            )


class TestDeleteForImport:
    @pytest.mark.asyncio
    async def test_removes_all_persona_batches_for_import(self, repo_and_coll):
        repo, _coll = repo_and_coll
        await repo.ensure_batch(
            import_id="imp1", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=1,
        )
        await repo.ensure_batch(
            import_id="imp1", persona_id="p2", user_id="u1",
            model_unique_id="conn:m", target_count=1,
        )
        # An unrelated import — must survive.
        await repo.ensure_batch(
            import_id="imp2", persona_id="p1", user_id="u1",
            model_unique_id="conn:m", target_count=1,
        )

        deleted = await repo.delete_for_import("imp1")
        assert deleted == 2
        assert await repo.get("imp1", "p1") is None
        assert await repo.get("imp1", "p2") is None
        assert await repo.get("imp2", "p1") is not None
