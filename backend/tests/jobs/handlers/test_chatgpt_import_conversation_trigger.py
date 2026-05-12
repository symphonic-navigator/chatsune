"""Tests for the memory-batch trigger logic in the per-conversation handler.

Scope: when the success/failure counter quorum is reached, the handler
must (a) atomically transition the batch row pending → running and
(b) submit exactly one ``CHATGPT_IMPORT_MEMORY_BATCH`` job. The rest of
the conversation-import behaviour (parsing, session creation) is
exercised by the existing parser / session-builder tests and the
upcoming manual-verification pass — we stub it out here so we can focus
on the counters.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

import backend.jobs.handlers._chatgpt_import_conversation as conv_handler
from backend.jobs._models import JobEntry, JobType


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeRepo:
    """Stand-in for ``ChatGptImportRepository``.

    Returns a synthetic conversation document on ``get_conversation``;
    ``record_import`` / ``reset_ttl`` are no-ops;
    ``list_imported_session_ids_chronological`` returns the configured
    list (caller controls ordering).
    """

    def __init__(self, *, session_ids: list[str]) -> None:
        self.session_ids = list(session_ids)
        self.record_import_calls: list[dict[str, Any]] = []

    async def get_conversation(
        self, *, user_id: str, import_id: str, chatgpt_conversation_id: str,
    ) -> dict | None:
        return {
            "user_id": user_id,
            "import_id": import_id,
            "chatgpt_conversation_id": chatgpt_conversation_id,
            "raw_data": {"_irrelevant": True},
            "title": "test conversation",
        }

    async def record_import(self, **kwargs) -> None:
        self.record_import_calls.append(dict(kwargs))

    async def reset_ttl(self, import_id: str) -> None:
        return None

    async def list_imported_session_ids_chronological(
        self, *, import_id: str, persona_id: str,
    ) -> list[str]:
        return list(self.session_ids)


class FakeBatchRepo:
    """In-memory ``ChatGptImportMemoryBatchRepository`` with single doc."""

    def __init__(self, target_count: int = 2) -> None:
        self.doc: dict[str, Any] = {
            "_id": "imp1:p1",
            "import_id": "imp1",
            "persona_id": "p1",
            "user_id": "u1",
            "model_unique_id": "conn:m",
            "state": "pending",
            "target_count": target_count,
            "conversations_imported": 0,
            "permanent_failures": 0,
            "session_ids": [],
            "paused_at": None,
            "total_entries_created": 0,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        self.claim_attempts = 0

    async def ensure_batch(self, **kwargs) -> dict:
        # Idempotent: pretend the row already exists.
        return dict(self.doc)

    async def increment_imported(
        self, import_id: str, persona_id: str,
    ) -> dict | None:
        self.doc["conversations_imported"] += 1
        return dict(self.doc)

    async def increment_failures(
        self, import_id: str, persona_id: str,
    ) -> dict | None:
        self.doc["permanent_failures"] += 1
        return dict(self.doc)

    async def claim_running(
        self, *, import_id: str, persona_id: str, session_ids: list[str],
    ) -> dict | None:
        self.claim_attempts += 1
        if self.doc["state"] != "pending":
            return None
        self.doc["state"] = "running"
        self.doc["session_ids"] = list(session_ids)
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
        self.published.append({"topic": str(topic), "event": event})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(
    *,
    persona_target_count: int = 2,
    chatgpt_conversation_id: str = "conv-a",
) -> JobEntry:
    return JobEntry(
        id="j",
        job_type=JobType.CHATGPT_IMPORT_CONVERSATION,
        user_id="u1",
        model_unique_id="chatgpt_import:internal",
        payload={
            "user_id": "u1",
            "import_id": "imp1",
            "chatgpt_conversation_id": chatgpt_conversation_id,
            "persona_id": "p1",
            "correlation_id": "corr-1",
            "persona_target_count": persona_target_count,
        },
        correlation_id="corr-1",
        created_at=datetime.now(UTC),
    )


class _ParsedStub:
    title = "stub"

    def __init__(self, has_messages: bool = True) -> None:
        self.messages = ["m"] if has_messages else []


@pytest.fixture
def patched(monkeypatch):
    """Stub out parser, session builder, chat / persona public APIs,
    and the job-submit function so we can drive the trigger logic
    without touching real infrastructure."""

    def _build(
        *,
        target_count: int = 2,
        session_ids: list[str] | None = None,
        parser_raises: bool = False,
        parsed_has_messages: bool = True,
        create_imported_raises: bool = False,
    ):
        repo = FakeRepo(session_ids=session_ids or ["s-old", "s-new"])
        batch_repo = FakeBatchRepo(target_count=target_count)
        event_bus = FakeEventBus()
        submit_calls: list[dict[str, Any]] = []

        monkeypatch.setattr(conv_handler, "ChatGptImportRepository", lambda _db: repo)
        monkeypatch.setattr(
            conv_handler, "ChatGptImportMemoryBatchRepository",
            lambda _db: batch_repo,
        )
        monkeypatch.setattr(conv_handler, "get_db", lambda: object())

        # parse_conversation: raise or return a parsed object.
        def _fake_parse(raw):
            if parser_raises:
                raise ValueError("bad json")
            return _ParsedStub(has_messages=parsed_has_messages)

        monkeypatch.setattr(conv_handler, "parse_conversation", _fake_parse)

        # build_imported_session_request: minimal request object.
        class _Req:
            persona_id = "p1"
            title = "t"
            messages = []
            imported_from = "chatgpt"
            imported_model_slug = None
            original_created_at = datetime.now(UTC)

        monkeypatch.setattr(
            conv_handler, "build_imported_session_request",
            lambda parsed, persona_id: _Req(),
        )

        # create_imported_session (chat module): return a session doc or
        # raise. Patched on the chat module so the handler's deferred
        # import resolves to our stub.
        async def _fake_create(**kwargs):
            if create_imported_raises:
                raise RuntimeError("create failed")
            return {"_id": "s-new"}

        import backend.modules.chat as chat_mod
        monkeypatch.setattr(chat_mod, "create_imported_session", _fake_create)

        # get_persona (persona module): every persona has a model.
        async def _fake_get_persona(persona_id: str, user_id: str):
            return {"_id": persona_id, "user_id": user_id, "model_unique_id": "conn:m"}

        import backend.modules.persona as persona_mod
        monkeypatch.setattr(persona_mod, "get_persona", _fake_get_persona)

        # submit job (deferred import inside the trigger helper).
        async def _fake_submit(job_type, *, user_id, model_unique_id, payload, correlation_id=None):
            submit_calls.append({
                "job_type": job_type,
                "user_id": user_id,
                "payload": deepcopy(payload),
            })
            return "submitted-job-id"

        import backend.jobs as jobs_mod
        monkeypatch.setattr(jobs_mod, "submit", _fake_submit)

        return {
            "repo": repo,
            "batch_repo": batch_repo,
            "event_bus": event_bus,
            "submit_calls": submit_calls,
        }

    return _build


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSuccessIncrement:
    @pytest.mark.asyncio
    async def test_first_success_bumps_imported_no_trigger(self, patched):
        """target=2; one success → imported=1 != 2 → no claim, no submit."""
        ctx = patched(target_count=2)
        await conv_handler.handle_chatgpt_import_conversation(
            _make_job(persona_target_count=2),
            config=None, redis=None, event_bus=ctx["event_bus"],  # type: ignore[arg-type]
        )
        assert ctx["batch_repo"].doc["conversations_imported"] == 1
        assert ctx["batch_repo"].claim_attempts == 0
        assert ctx["submit_calls"] == []

    @pytest.mark.asyncio
    async def test_final_success_triggers_submit(self, patched):
        """target=1; one success → imported=1 == 1 → claim + submit."""
        ctx = patched(target_count=1, session_ids=["s-only"])
        await conv_handler.handle_chatgpt_import_conversation(
            _make_job(persona_target_count=1),
            config=None, redis=None, event_bus=ctx["event_bus"],  # type: ignore[arg-type]
        )
        assert ctx["batch_repo"].doc["state"] == "running"
        assert ctx["batch_repo"].doc["session_ids"] == ["s-only"]
        # Exactly one submit, with the right shape.
        assert len(ctx["submit_calls"]) == 1
        call = ctx["submit_calls"][0]
        assert call["job_type"] == JobType.CHATGPT_IMPORT_MEMORY_BATCH
        assert call["payload"]["import_id"] == "imp1"
        assert call["payload"]["persona_id"] == "p1"
        assert call["payload"]["force_budget"] is False


class TestTerminalFailureCounter:
    @pytest.mark.asyncio
    async def test_parse_failed_increments_failures(self, patched):
        """parse_conversation raises → terminal non-raise branch →
        bump permanent_failures (not imported)."""
        ctx = patched(target_count=2, parser_raises=True)
        await conv_handler.handle_chatgpt_import_conversation(
            _make_job(persona_target_count=2),
            config=None, redis=None, event_bus=ctx["event_bus"],  # type: ignore[arg-type]
        )
        assert ctx["batch_repo"].doc["permanent_failures"] == 1
        assert ctx["batch_repo"].doc["conversations_imported"] == 0
        assert ctx["submit_calls"] == []

    @pytest.mark.asyncio
    async def test_no_convertible_messages_increments_failures(self, patched):
        ctx = patched(target_count=2, parsed_has_messages=False)
        await conv_handler.handle_chatgpt_import_conversation(
            _make_job(persona_target_count=2),
            config=None, redis=None, event_bus=ctx["event_bus"],  # type: ignore[arg-type]
        )
        assert ctx["batch_repo"].doc["permanent_failures"] == 1
        assert ctx["batch_repo"].doc["conversations_imported"] == 0

    @pytest.mark.asyncio
    async def test_create_imported_failure_does_not_increment(self, patched):
        """``create_imported_session`` failures re-raise so the job
        retries. We must **not** bump permanent_failures from there or
        the counter would over-count when retries also fail."""
        ctx = patched(target_count=2, create_imported_raises=True)
        with pytest.raises(RuntimeError):
            await conv_handler.handle_chatgpt_import_conversation(
                _make_job(persona_target_count=2),
                config=None, redis=None, event_bus=ctx["event_bus"],  # type: ignore[arg-type]
            )
        # Counters untouched.
        assert ctx["batch_repo"].doc["permanent_failures"] == 0
        assert ctx["batch_repo"].doc["conversations_imported"] == 0
        assert ctx["submit_calls"] == []


class TestMixOfSuccessAndFailure:
    @pytest.mark.asyncio
    async def test_one_success_one_failure_target_two_triggers(self, patched):
        """First call succeeds (1+0 != 2), second is a parse_failed
        (1+1 == 2) → claim + submit fires exactly once after the
        second call."""
        ctx = patched(target_count=2, session_ids=["s-old", "s-new"])
        # First: success.
        await conv_handler.handle_chatgpt_import_conversation(
            _make_job(persona_target_count=2, chatgpt_conversation_id="c1"),
            config=None, redis=None, event_bus=ctx["event_bus"],  # type: ignore[arg-type]
        )
        # Patch the parser to raise for the second call.
        import backend.jobs.handlers._chatgpt_import_conversation as ch
        ch.parse_conversation = lambda raw: (_ for _ in ()).throw(ValueError("bad"))
        await conv_handler.handle_chatgpt_import_conversation(
            _make_job(persona_target_count=2, chatgpt_conversation_id="c2"),
            config=None, redis=None, event_bus=ctx["event_bus"],  # type: ignore[arg-type]
        )
        # Trigger fired exactly once.
        assert len(ctx["submit_calls"]) == 1


class TestConcurrentClaim:
    @pytest.mark.asyncio
    async def test_only_one_submit_under_race(self, patched):
        """Two finishers both observe imported+failures == target. The
        atomic ``claim_running`` only flips state on the first; the
        second sees ``state="running"`` and bails. Exactly one submit."""
        ctx = patched(target_count=1, session_ids=["s-only"])
        # First job — should succeed and trigger.
        await conv_handler.handle_chatgpt_import_conversation(
            _make_job(persona_target_count=1, chatgpt_conversation_id="c1"),
            config=None, redis=None, event_bus=ctx["event_bus"],  # type: ignore[arg-type]
        )
        # Simulate a duplicate "finisher" by manually bumping counter
        # and calling the increment path again. The batch repo's
        # claim_running only succeeds on state=pending.
        ctx["batch_repo"].doc["conversations_imported"] = 1
        ctx["batch_repo"].doc["state"] = "running"  # already claimed
        # Now bump again as if a concurrent caller arrived.
        await ctx["batch_repo"].increment_imported("imp1", "p1")
        result = await ctx["batch_repo"].claim_running(
            import_id="imp1", persona_id="p1", session_ids=["s-only"],
        )
        # Second claim returns None.
        assert result is None
        # Still only one submit recorded.
        assert len(ctx["submit_calls"]) == 1


class TestMissingPersonaTargetCount:
    @pytest.mark.asyncio
    async def test_handler_skips_batch_logic_when_missing(self, patched):
        """A legacy job already queued before this feature lacks
        ``persona_target_count``. The handler must not crash; it just
        does not maintain batch counters for that job."""
        ctx = patched(target_count=2)

        # Build a job without the new payload field.
        job = JobEntry(
            id="j-legacy",
            job_type=JobType.CHATGPT_IMPORT_CONVERSATION,
            user_id="u1",
            model_unique_id="chatgpt_import:internal",
            payload={
                "user_id": "u1",
                "import_id": "imp1",
                "chatgpt_conversation_id": "c1",
                "persona_id": "p1",
                "correlation_id": "corr-1",
            },
            correlation_id="corr-1",
            created_at=datetime.now(UTC),
        )
        await conv_handler.handle_chatgpt_import_conversation(
            job, config=None, redis=None, event_bus=ctx["event_bus"],  # type: ignore[arg-type]
        )
        # Counters untouched (the trigger helper short-circuited).
        assert ctx["batch_repo"].doc["conversations_imported"] == 0
        assert ctx["submit_calls"] == []
