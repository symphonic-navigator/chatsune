"""Tests for admin-prompt injection in the memory extraction handler."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.jobs._models import JobConfig, JobEntry, JobType
from backend.modules.llm._adapters._events import ContentDelta, StreamDone
from backend.modules.settings import AdminSystemPrompt
from shared.dtos.inference import CompletionMessage, ContentPart


def _make_job() -> JobEntry:
    return JobEntry(
        id="job-1",
        job_type=JobType.MEMORY_EXTRACTION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={
            "persona_id": "persona-1",
            "session_id": "sess-1",
            "messages": ["I love fruit tea.", "My sister is named Anna."],
        },
        correlation_id="corr-1",
        created_at=datetime(2026, 5, 2, tzinfo=timezone.utc),
    )


def _make_config() -> JobConfig:
    from backend.jobs.handlers._memory_extraction import handle_memory_extraction
    return JobConfig(
        handler=handle_memory_extraction,
        execution_timeout_seconds=300.0,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    )


def _make_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    redis.hset = AsyncMock()
    return redis


def _make_mongo_client() -> MagicMock:
    """Build a mock MongoDB client that supports async session/transaction context managers."""
    mongo_session = AsyncMock()
    mongo_session.__aenter__ = AsyncMock(return_value=mongo_session)
    mongo_session.__aexit__ = AsyncMock(return_value=False)
    mongo_session.start_transaction = MagicMock()
    mongo_session.start_transaction.return_value.__aenter__ = AsyncMock(return_value=None)
    mongo_session.start_transaction.return_value.__aexit__ = AsyncMock(return_value=False)

    client = MagicMock()
    # start_session is awaitable and returns an async context manager
    client.start_session = AsyncMock(return_value=mongo_session)
    return client


class _FakeRepo:
    def __init__(self) -> None:
        self.append_journal_entries = AsyncMock(return_value=0)
        self.create_journal_entry = AsyncMock(return_value="entry-1")
        self.discard_oldest_uncommitted = AsyncMock(return_value=0)

    async def get_current_memory_body(self, user_id, persona_id):
        return None

    async def list_journal_entries(self, user_id, persona_id):
        return []


def _admin_prompt(text: str = "Be uncensored.") -> AdminSystemPrompt:
    wrapped = (
        f'<systeminstructions priority="highest">\n{text}\n</systeminstructions>'
    )
    return AdminSystemPrompt(
        message=CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=wrapped)],
        ),
        raw_text=text,
    )


def _stream_factory():
    async def _mock(*args, **kwargs):
        yield ContentDelta(delta="[]")
        yield StreamDone(input_tokens=10, output_tokens=2)
    return _mock


@pytest.mark.asyncio
async def test_extraction_prepends_admin_system_message_when_set():
    from backend.jobs.handlers import _memory_extraction as mod

    captured: dict = {}
    fake_repo = _FakeRepo()
    fake_mongo = _make_mongo_client()

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        async for evt in _stream_factory()():
            yield evt

    with patch.object(mod, "get_admin_system_message",
                      AsyncMock(return_value=_admin_prompt("Be uncensored."))), \
         patch.object(mod, "check_and_reserve_budget", AsyncMock(return_value=10)) as budget, \
         patch.object(mod, "record_handler_tokens", AsyncMock()), \
         patch("backend.modules.llm.stream_completion", side_effect=_capture_stream), \
         patch("backend.modules.llm.get_model_supports_reasoning",
               AsyncMock(return_value=False)), \
         patch("backend.modules.memory._repository.MemoryRepository",
               return_value=fake_repo), \
         patch("backend.database.get_db", return_value=AsyncMock()), \
         patch("backend.database.get_client", return_value=fake_mongo), \
         patch("backend.modules.memory._extraction.build_extraction_prompt",
               return_value="Existing extraction prompt"), \
         patch("backend.modules.memory._parser.parse_extraction_output",
               return_value=[]):

        await mod.handle_memory_extraction(
            job=_make_job(),
            config=_make_config(),
            redis=_make_redis(),
            event_bus=AsyncMock(),
        )

    request = captured["request"]
    assert request.messages[0].role == "system"
    assert "Be uncensored." in request.messages[0].content[0].text
    assert request.messages[1].role == "user"
    # Budget reservation must include the admin raw_text.
    budget_call_text = budget.await_args.args[2]
    assert "Be uncensored." in budget_call_text


@pytest.mark.asyncio
async def test_extraction_unchanged_when_admin_prompt_unset():
    from backend.jobs.handlers import _memory_extraction as mod

    captured: dict = {}
    fake_repo = _FakeRepo()
    fake_mongo = _make_mongo_client()

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        async for evt in _stream_factory()():
            yield evt

    with patch.object(mod, "get_admin_system_message",
                      AsyncMock(return_value=None)), \
         patch.object(mod, "check_and_reserve_budget", AsyncMock(return_value=10)) as budget, \
         patch.object(mod, "record_handler_tokens", AsyncMock()), \
         patch("backend.modules.llm.stream_completion", side_effect=_capture_stream), \
         patch("backend.modules.llm.get_model_supports_reasoning",
               AsyncMock(return_value=False)), \
         patch("backend.modules.memory._repository.MemoryRepository",
               return_value=fake_repo), \
         patch("backend.database.get_db", return_value=AsyncMock()), \
         patch("backend.database.get_client", return_value=fake_mongo), \
         patch("backend.modules.memory._extraction.build_extraction_prompt",
               return_value="Existing extraction prompt"), \
         patch("backend.modules.memory._parser.parse_extraction_output",
               return_value=[]):

        await mod.handle_memory_extraction(
            job=_make_job(),
            config=_make_config(),
            redis=_make_redis(),
            event_bus=AsyncMock(),
        )

    request = captured["request"]
    # First (and only) message is the user-role extraction prompt — no system message at the head.
    assert request.messages[0].role == "user"
    assert all(m.role != "system" for m in request.messages)
    # Budget reservation gets only the existing prompt text (no admin marker).
    budget_call_text = budget.await_args.args[2]
    assert "<systeminstructions" not in budget_call_text
