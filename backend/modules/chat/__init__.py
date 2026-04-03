"""Chat module — sessions, messages, inference orchestration.

Public API: import only from this file.
"""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.chat._handlers import router
from backend.modules.chat._inference import InferenceRunner
from backend.modules.chat._repository import ChatRepository
from backend.database import get_db
from backend.modules.llm import (
    stream_completion as llm_stream_completion,
    LlmCredentialNotFoundError,
)
from backend.modules.persona import get_persona
from backend.ws.event_bus import get_event_bus
from backend.ws.manager import get_manager
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.events.chat import (
    ChatContentDeltaEvent,
    ChatStreamEndedEvent,
    ChatStreamErrorEvent,
    ChatStreamStartedEvent,
    ChatThinkingDeltaEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)

_runner = InferenceRunner()

# Active cancel events keyed by correlation_id
_cancel_events: dict[str, asyncio.Event] = {}


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the chat module collections."""
    await ChatRepository(db).create_indexes()


async def handle_chat_send(user_id: str, data: dict) -> None:
    """Handle a chat.send WebSocket message — run inference for the session."""
    session_id = data.get("session_id")
    content_parts = data.get("content")
    if not session_id or not content_parts:
        return

    db = get_db()
    repo = ChatRepository(db)

    session = await repo.get_session(session_id, user_id)
    if not session:
        return

    # Join text content parts into a single string
    text = "".join(
        part.get("text", "") for part in content_parts if part.get("type") == "text"
    ).strip()
    if not text:
        return

    # Save the user message
    await repo.save_message(session_id, role="user", content=text, token_count=0)

    # Set session state to streaming
    await repo.update_session_state(session_id, "streaming")

    # Load persona for system prompt
    persona = await get_persona(session.get("persona_id", ""), user_id)
    system_prompt = persona.get("system_prompt", "") if persona else ""

    # Load message history
    history_docs = await repo.list_messages(session_id)
    messages: list[CompletionMessage] = []

    if system_prompt:
        messages.append(CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=system_prompt)],
        ))

    for doc in history_docs:
        messages.append(CompletionMessage(
            role=doc["role"],
            content=[ContentPart(type="text", text=doc["content"])],
        ))

    # Parse provider and model from the session's model_unique_id
    model_unique_id = session.get("model_unique_id", "")
    if ":" not in model_unique_id:
        _log.error("Invalid model_unique_id format: %s", model_unique_id)
        await repo.update_session_state(session_id, "idle")
        return

    provider_id, model_slug = model_unique_id.split(":", 1)

    request = CompletionRequest(
        model=model_slug,
        messages=messages,
        temperature=persona.get("temperature") if persona else None,
        reasoning_enabled=persona.get("reasoning_enabled", False) if persona else False,
    )

    correlation_id = str(uuid4())
    cancel_event = asyncio.Event()
    _cancel_events[correlation_id] = cancel_event

    manager = get_manager()
    event_bus = get_event_bus()

    # Delta events go directly to user (no persistence); lifecycle events go via event bus
    _DELTA_TYPES = {Topics.CHAT_CONTENT_DELTA, Topics.CHAT_THINKING_DELTA}

    async def emit_fn(event) -> None:
        event_dict = event.model_dump(mode="json")
        event_type = event_dict.get("type", "")

        if event_type in _DELTA_TYPES:
            # Send deltas directly to user — high frequency, ephemeral
            await manager.send_to_user(user_id, event_dict)
        else:
            # Lifecycle events go through event bus for persistence and fan-out
            await event_bus.publish(
                event_type,
                event,
                scope=f"session:{session_id}",
                target_user_ids=[user_id],
                correlation_id=correlation_id,
            )

    def stream_fn():
        return llm_stream_completion(user_id, provider_id, request)

    async def save_fn(content: str, thinking: str | None, usage: dict | None) -> None:
        token_count = usage.get("output_tokens", 0) if usage else 0
        await repo.save_message(
            session_id,
            role="assistant",
            content=content,
            token_count=token_count,
            thinking=thinking,
        )
        await repo.update_session_state(session_id, "idle")

    try:
        await _runner.run(
            user_id=user_id,
            session_id=session_id,
            correlation_id=correlation_id,
            stream_fn=stream_fn,
            emit_fn=emit_fn,
            save_fn=save_fn,
            cancel_event=cancel_event,
        )
    except LlmCredentialNotFoundError:
        now = datetime.now(timezone.utc)
        await emit_fn(ChatStreamStartedEvent(
            session_id=session_id, correlation_id=correlation_id, timestamp=now,
        ))
        await emit_fn(ChatStreamErrorEvent(
            correlation_id=correlation_id,
            error_code="credential_not_found",
            recoverable=False,
            user_message="No API key configured for this model's provider. Please add one in settings.",
            timestamp=now,
        ))
        await emit_fn(ChatStreamEndedEvent(
            correlation_id=correlation_id,
            session_id=session_id,
            status="error",
            usage=None,
            context_status="green",
            timestamp=now,
        ))
        await repo.update_session_state(session_id, "idle")
    except Exception as e:
        _log.error("Unexpected error in handle_chat_send for session %s: %s", session_id, e)
        await repo.update_session_state(session_id, "idle")
    finally:
        _cancel_events.pop(correlation_id, None)


def handle_chat_cancel(user_id: str, data: dict) -> None:
    """Handle a chat.cancel WebSocket message — signal cancellation."""
    correlation_id = data.get("correlation_id")
    if correlation_id and correlation_id in _cancel_events:
        _cancel_events[correlation_id].set()


__all__ = ["router", "init_indexes", "handle_chat_send", "handle_chat_cancel"]
