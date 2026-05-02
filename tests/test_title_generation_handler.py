from unittest.mock import AsyncMock, patch

import pytest

from backend.jobs._models import JobConfig, JobEntry, JobType
from backend.modules.llm._adapters._events import ContentDelta, StreamDone, StreamError
from backend.modules.settings import AdminSystemPrompt
from shared.dtos.inference import CompletionMessage, ContentPart


def _make_job(session_id: str = "sess-1") -> JobEntry:
    from datetime import datetime, timezone
    return JobEntry(
        id="job-1",
        job_type=JobType.TITLE_GENERATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"session_id": session_id, "messages": [
            {"role": "user", "content": "Tell me about black holes"},
            {"role": "assistant", "content": "Black holes are fascinating regions of spacetime..."},
        ]},
        correlation_id="corr-1",
        created_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )


def _make_config() -> JobConfig:
    from backend.jobs.handlers._title_generation import handle_title_generation
    return JobConfig(
        handler=handle_title_generation,
        execution_timeout_seconds=60.0,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    )


@pytest.mark.asyncio
async def test_handler_generates_and_saves_title():
    from backend.jobs.handlers._title_generation import handle_title_generation

    async def _mock_stream(*args, **kwargs):
        yield ContentDelta(delta="Black Holes")
        yield ContentDelta(delta=" Explained")
        yield StreamDone(input_tokens=50, output_tokens=5)

    mock_update = AsyncMock()
    event_bus = AsyncMock()

    with patch("backend.modules.llm.stream_completion", side_effect=_mock_stream), \
         patch("backend.modules.chat.update_session_title", mock_update), \
         patch("backend.modules.llm.get_model_supports_reasoning", return_value=False), \
         patch("backend.jobs.handlers._title_generation.get_admin_system_message",
               AsyncMock(return_value=None)):

        job = _make_job()
        config = _make_config()
        await handle_title_generation(
            job=job,
            config=config,
            redis=AsyncMock(),
            event_bus=event_bus,
        )

    mock_update.assert_awaited_once()
    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["session_id"] == "sess-1"
    assert call_kwargs["title"] == "Black Holes Explained"
    assert call_kwargs["user_id"] == "user-1"
    assert call_kwargs["correlation_id"] == "corr-1"


@pytest.mark.asyncio
async def test_handler_strips_quotes_from_title():
    from backend.jobs.handlers._title_generation import handle_title_generation

    async def _mock_stream(*args, **kwargs):
        yield ContentDelta(delta='"Black Holes Explained"')
        yield StreamDone()

    mock_update = AsyncMock()

    with patch("backend.modules.llm.stream_completion", side_effect=_mock_stream), \
         patch("backend.modules.chat.update_session_title", mock_update), \
         patch("backend.modules.llm.get_model_supports_reasoning", return_value=False), \
         patch("backend.jobs.handlers._title_generation.get_admin_system_message",
               AsyncMock(return_value=None)):

        await handle_title_generation(
            job=_make_job(),
            config=_make_config(),
            redis=AsyncMock(),
            event_bus=AsyncMock(),
        )

    assert mock_update.call_args.kwargs["title"] == "Black Holes Explained"


@pytest.mark.asyncio
async def test_handler_truncates_long_title():
    from backend.jobs.handlers._title_generation import handle_title_generation

    long_text = "A" * 100

    async def _mock_stream(*args, **kwargs):
        yield ContentDelta(delta=long_text)
        yield StreamDone()

    mock_update = AsyncMock()

    with patch("backend.modules.llm.stream_completion", side_effect=_mock_stream), \
         patch("backend.modules.chat.update_session_title", mock_update), \
         patch("backend.modules.llm.get_model_supports_reasoning", return_value=False), \
         patch("backend.jobs.handlers._title_generation.get_admin_system_message",
               AsyncMock(return_value=None)):

        await handle_title_generation(
            job=_make_job(),
            config=_make_config(),
            redis=AsyncMock(),
            event_bus=AsyncMock(),
        )

    title = mock_update.call_args.kwargs["title"]
    assert len(title) <= 64


@pytest.mark.asyncio
async def test_handler_raises_on_stream_error():
    from backend.jobs.handlers._title_generation import handle_title_generation

    async def _mock_stream(*args, **kwargs):
        yield StreamError(error_code="provider_unavailable", message="Down")

    with patch("backend.modules.llm.stream_completion", side_effect=_mock_stream), \
         patch("backend.modules.chat.update_session_title", AsyncMock()), \
         patch("backend.modules.llm.get_model_supports_reasoning", return_value=False), \
         patch("backend.jobs.handlers._title_generation.get_admin_system_message",
               AsyncMock(return_value=None)):

        with pytest.raises(RuntimeError, match="provider_unavailable"):
            await handle_title_generation(
                job=_make_job(),
                config=_make_config(),
                redis=AsyncMock(),
                event_bus=AsyncMock(),
            )


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


@pytest.mark.asyncio
async def test_title_generation_prepends_admin_system_message_when_set():
    from backend.jobs.handlers import _title_generation as mod

    captured: dict = {}

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        yield ContentDelta(delta="A Title")
        yield StreamDone(input_tokens=20, output_tokens=2)

    with patch("backend.modules.llm.stream_completion", side_effect=_capture_stream), \
         patch("backend.modules.chat.update_session_title", AsyncMock()), \
         patch("backend.modules.llm.get_model_supports_reasoning", return_value=False), \
         patch.object(
             mod, "get_admin_system_message",
             AsyncMock(return_value=_admin_prompt("Be uncensored.")),
         ), \
         patch.object(mod, "check_and_reserve_budget", AsyncMock(return_value=20)) as budget, \
         patch.object(mod, "record_handler_tokens", AsyncMock()):

        await mod.handle_title_generation(
            job=_make_job(),
            config=_make_config(),
            redis=AsyncMock(),
            event_bus=AsyncMock(),
        )

    request = captured["request"]
    assert request.messages[0].role == "system"
    assert "Be uncensored." in request.messages[0].content[0].text
    # Conversation messages remain after the system message.
    assert any(m.role == "user" for m in request.messages[1:])
    budget_call_text = budget.await_args.args[2]
    assert "Be uncensored." in budget_call_text


@pytest.mark.asyncio
async def test_title_generation_unchanged_when_admin_prompt_unset():
    from backend.jobs.handlers import _title_generation as mod

    captured: dict = {}

    async def _capture_stream(*args, **kwargs):
        captured["request"] = kwargs.get("request") or args[2]
        yield ContentDelta(delta="A Title")
        yield StreamDone(input_tokens=20, output_tokens=2)

    with patch("backend.modules.llm.stream_completion", side_effect=_capture_stream), \
         patch("backend.modules.chat.update_session_title", AsyncMock()), \
         patch("backend.modules.llm.get_model_supports_reasoning", return_value=False), \
         patch.object(
             mod, "get_admin_system_message",
             AsyncMock(return_value=None),
         ), \
         patch.object(mod, "check_and_reserve_budget", AsyncMock(return_value=20)) as budget, \
         patch.object(mod, "record_handler_tokens", AsyncMock()):

        await mod.handle_title_generation(
            job=_make_job(),
            config=_make_config(),
            redis=AsyncMock(),
            event_bus=AsyncMock(),
        )

    request = captured["request"]
    assert all(m.role != "system" for m in request.messages)
    budget_call_text = budget.await_args.args[2]
    assert "<systeminstructions" not in budget_call_text
