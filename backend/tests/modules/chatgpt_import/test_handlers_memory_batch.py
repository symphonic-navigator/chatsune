"""Tests for the memory-batch REST endpoints.

These call the handler functions in
``backend.modules.chatgpt_import._handlers`` directly, bypassing
FastAPI's routing layer. The state-machine semantics (404 vs. 409,
atomic resume claim, discard emits a Done event) are testable without
running a TestClient.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import HTTPException

import backend.modules.chatgpt_import._handlers as handlers_mod
from shared.dtos.chatgpt_import import (
    MemoryBatchDiscardRequest,
    MemoryBatchResumeRequest,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeBatchRepo:
    def __init__(self, doc: dict | None = None) -> None:
        self.doc = dict(doc) if doc else None
        self.claim_resume_attempts = 0
        self.mark_discarded_attempts = 0

    async def get(self, import_id: str, persona_id: str) -> dict | None:
        return dict(self.doc) if self.doc else None

    async def claim_resume(self, *, import_id: str, persona_id: str) -> dict | None:
        self.claim_resume_attempts += 1
        if self.doc and self.doc.get("state") == "paused":
            self.doc["state"] = "running"
            self.doc["paused_at"] = None
            return dict(self.doc)
        return None

    async def mark_discarded(
        self, *, import_id: str, persona_id: str, only_if_paused: bool = False,
    ) -> dict | None:
        self.mark_discarded_attempts += 1
        if self.doc is None:
            return None
        if only_if_paused and self.doc.get("state") != "paused":
            return None
        self.doc["state"] = "discarded"
        self.doc["paused_at"] = None
        return dict(self.doc)


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
        })


class FakeRedis:
    def __init__(self) -> None:
        self.delete_calls: list[str] = []

    async def delete(self, key: str) -> int:
        self.delete_calls.append(key)
        return 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(state: str = "paused", entries: int = 7) -> dict:
    return {
        "_id": "imp1:p1",
        "import_id": "imp1",
        "persona_id": "p1",
        "user_id": "u1",
        "model_unique_id": "conn:m",
        "state": state,
        "target_count": 3,
        "conversations_imported": 3,
        "permanent_failures": 0,
        "session_ids": ["s1", "s2", "s3"],
        "paused_at": {
            "session_index": 2,
            "session_id": "s2",
            "reason": "provider_unavailable",
            "user_message": "Provider not reachable",
            "detail": None,
            "at": datetime.now(UTC),
        } if state == "paused" else None,
        "total_entries_created": entries,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


@pytest.fixture
def patched(monkeypatch):
    def _build(
        *,
        doc: dict | None = None,
        persona_owns_user: bool = True,
    ):
        repo = FakeBatchRepo(doc)
        event_bus = FakeEventBus()
        redis = FakeRedis()
        submit_calls: list[dict[str, Any]] = []

        monkeypatch.setattr(
            handlers_mod, "ChatGptImportMemoryBatchRepository",
            lambda _db: repo,
        )
        monkeypatch.setattr(handlers_mod, "get_db", lambda: object())

        async def _fake_get_persona(persona_id: str, user_id: str):
            if not persona_owns_user:
                return None
            return {"_id": persona_id, "user_id": user_id, "model_unique_id": "conn:m"}

        monkeypatch.setattr(handlers_mod, "get_persona", _fake_get_persona)

        # Patch submit + get_redis + get_event_bus (deferred imports).
        async def _fake_submit(job_type, *, user_id, model_unique_id, payload, correlation_id=None):
            submit_calls.append({
                "job_type": job_type,
                "user_id": user_id,
                "model_unique_id": model_unique_id,
                "payload": dict(payload),
                "correlation_id": correlation_id,
            })
            return "job-id"

        import backend.jobs as jobs_mod
        monkeypatch.setattr(jobs_mod, "submit", _fake_submit)

        import backend.database as database_mod
        monkeypatch.setattr(database_mod, "get_redis", lambda: redis)

        import backend.ws.event_bus as event_bus_mod
        monkeypatch.setattr(event_bus_mod, "get_event_bus", lambda: event_bus)

        return {
            "repo": repo,
            "event_bus": event_bus,
            "redis": redis,
            "submit_calls": submit_calls,
        }

    return _build


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


class TestResume:
    @pytest.mark.asyncio
    async def test_returns_404_if_no_batch(self, patched):
        patched(doc=None)
        with pytest.raises(HTTPException) as exc:
            await handlers_mod.resume_memory_batch(
                import_id="imp1",
                body=MemoryBatchResumeRequest(persona_id="p1", force_budget=False),
                user={"sub": "u1"},
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_409_when_not_paused(self, patched):
        patched(doc=_make_doc(state="running"))
        with pytest.raises(HTTPException) as exc:
            await handlers_mod.resume_memory_batch(
                import_id="imp1",
                body=MemoryBatchResumeRequest(persona_id="p1", force_budget=False),
                user={"sub": "u1"},
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_submits_job_with_force_budget(self, patched):
        ctx = patched(doc=_make_doc(state="paused"))
        dto = await handlers_mod.resume_memory_batch(
            import_id="imp1",
            body=MemoryBatchResumeRequest(persona_id="p1", force_budget=True),
            user={"sub": "u1"},
        )
        assert dto.state == "running"
        # Job was submitted once with the force_budget flag.
        assert len(ctx["submit_calls"]) == 1
        call = ctx["submit_calls"][0]
        assert call["payload"]["force_budget"] is True
        assert call["payload"]["import_id"] == "imp1"
        assert call["payload"]["persona_id"] == "p1"
        # Slot was released so the new batch job can re-acquire it
        # cleanly on its next run.
        assert any("u1:p1" in k for k in ctx["redis"].delete_calls)

    @pytest.mark.asyncio
    async def test_persona_not_owned_404(self, patched):
        patched(doc=_make_doc(state="paused"), persona_owns_user=False)
        with pytest.raises(HTTPException) as exc:
            await handlers_mod.resume_memory_batch(
                import_id="imp1",
                body=MemoryBatchResumeRequest(persona_id="p1", force_budget=False),
                user={"sub": "u1"},
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Discard
# ---------------------------------------------------------------------------


class TestDiscard:
    @pytest.mark.asyncio
    async def test_returns_409_when_not_paused(self, patched):
        patched(doc=_make_doc(state="running"))
        with pytest.raises(HTTPException) as exc:
            await handlers_mod.discard_memory_batch(
                import_id="imp1",
                body=MemoryBatchDiscardRequest(persona_id="p1"),
                user={"sub": "u1"},
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_discard_releases_slot_and_emits_done_event(self, patched):
        ctx = patched(doc=_make_doc(state="paused", entries=11))
        dto = await handlers_mod.discard_memory_batch(
            import_id="imp1",
            body=MemoryBatchDiscardRequest(persona_id="p1"),
            user={"sub": "u1"},
        )
        assert dto.state == "discarded"
        # Slot released.
        assert any("u1:p1" in k for k in ctx["redis"].delete_calls)
        # Done event published with correct total_entries_created.
        done = [
            p for p in ctx["event_bus"].published
            if p["topic"] == "chatgpt_import.memory.done"
        ]
        assert len(done) == 2  # both scopes
        for p in done:
            assert p["event"].total_entries_created == 11

    @pytest.mark.asyncio
    async def test_returns_404_if_no_batch(self, patched):
        patched(doc=None)
        with pytest.raises(HTTPException) as exc:
            await handlers_mod.discard_memory_batch(
                import_id="imp1",
                body=MemoryBatchDiscardRequest(persona_id="p1"),
                user={"sub": "u1"},
            )
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


class TestGet:
    @pytest.mark.asyncio
    async def test_returns_404_when_missing(self, patched):
        patched(doc=None)
        with pytest.raises(HTTPException) as exc:
            await handlers_mod.get_memory_batch(
                import_id="imp1", persona_id="p1", user={"sub": "u1"},
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_dto_for_existing(self, patched):
        patched(doc=_make_doc(state="paused", entries=4))
        dto = await handlers_mod.get_memory_batch(
            import_id="imp1", persona_id="p1", user={"sub": "u1"},
        )
        assert dto.import_id == "imp1"
        assert dto.persona_id == "p1"
        assert dto.state == "paused"
        assert dto.total_entries_created == 4
        assert dto.paused_at is not None
        assert dto.paused_at.reason == "provider_unavailable"

    @pytest.mark.asyncio
    async def test_returns_404_when_user_mismatch(self, patched):
        """Defence-in-depth: a row owned by a different user must yield 404."""
        doc = _make_doc(state="paused")
        doc["user_id"] = "u2"
        patched(doc=doc)
        with pytest.raises(HTTPException) as exc:
            await handlers_mod.get_memory_batch(
                import_id="imp1", persona_id="p1", user={"sub": "u1"},
            )
        assert exc.value.status_code == 404
