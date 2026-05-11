"""Long-running parse job for ChatGPT export uploads.

Streams a temp file with ijson, inserts one document per conversation
into ``chatgpt_import_conversations``, emits progress events every 10
conversations, and finally marks the parent import as ``ready`` (or
``failed`` if >50% of conversations could not be parsed).
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import structlog

from backend.database import get_db
from backend.jobs._models import JobConfig, JobEntry
from backend.modules.chatgpt_import._parser import (
    iter_conversations_from_file,
    parse_conversation,
)
from backend.modules.chatgpt_import._repository import ChatGptImportRepository
from shared.events.chatgpt_import import (
    ChatGptImportParseDoneEvent,
    ChatGptImportParseFailedEvent,
    ChatGptImportParseProgressEvent,
    ChatGptImportParseStartedEvent,
)
from shared.topics import Topics

_log = structlog.get_logger(__name__)
_PROGRESS_EVERY = 10


async def handle_chatgpt_import_parse(
    job: JobEntry,
    config: JobConfig,
    redis,
    event_bus,
) -> None:
    payload = job.payload
    user_id = payload["user_id"]
    import_id = payload["import_id"]
    file_path = Path(payload["file_path"])
    filename = payload["filename"]
    file_size_bytes = payload["file_size_bytes"]
    correlation_id = payload.get("correlation_id") or job.correlation_id

    db = get_db()
    repo = ChatGptImportRepository(db)

    scope = f"chatgpt_import:{import_id}"

    await event_bus.publish(
        Topics.CHATGPT_IMPORT_PARSE_STARTED,
        ChatGptImportParseStartedEvent(
            import_id=import_id,
            filename=filename,
            file_size_bytes=file_size_bytes,
            correlation_id=correlation_id,
            timestamp=datetime.now(UTC),
        ),
        scope=scope,
        target_user_ids=[user_id],
        correlation_id=correlation_id,
    )

    indexed = 0
    skipped_count = 0
    skipped_reasons: dict[str, int] = {}

    try:
        if not file_path.exists():
            raise FileNotFoundError(f"upload temp file missing: {file_path}")

        for conv in iter_conversations_from_file(str(file_path)):
            try:
                parsed = parse_conversation(conv)
                await repo.insert_conversation(
                    import_id=import_id,
                    user_id=user_id,
                    chatgpt_conversation_id=parsed.chatgpt_conversation_id,
                    title=parsed.title,
                    create_time=parsed.create_time,
                    update_time=parsed.update_time,
                    default_model_slug=parsed.default_model_slug,
                    message_count=parsed.message_count,
                    first_user_message_preview=parsed.first_user_message_preview,
                    first_assistant_message_preview=parsed.first_assistant_message_preview,
                    raw_data=conv,
                )
                indexed += 1
                if indexed % _PROGRESS_EVERY == 0:
                    await event_bus.publish(
                        Topics.CHATGPT_IMPORT_PARSE_PROGRESS,
                        ChatGptImportParseProgressEvent(
                            import_id=import_id,
                            conversations_indexed=indexed,
                            correlation_id=correlation_id,
                            timestamp=datetime.now(UTC),
                        ),
                        scope=scope,
                        target_user_ids=[user_id],
                        correlation_id=correlation_id,
                    )
            except Exception as exc:  # noqa: BLE001 - skip-and-continue is intentional
                skipped_count += 1
                reason = type(exc).__name__
                skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
                _log.warning(
                    "chatgpt_import.conversation_skipped",
                    import_id=import_id,
                    reason=reason,
                    error=str(exc)[:200],
                )

        total = indexed + skipped_count
        if total > 0 and skipped_count / total > 0.5:
            error_message = (
                f"More than half of conversations failed to parse "
                f"({skipped_count}/{total})"
            )
            await repo.update_import_status(
                import_id,
                status="failed",
                conversation_count=indexed,
                skipped_count=skipped_count,
                skipped_reasons=skipped_reasons,
                error_message=error_message,
            )
            await event_bus.publish(
                Topics.CHATGPT_IMPORT_PARSE_FAILED,
                ChatGptImportParseFailedEvent(
                    import_id=import_id,
                    error_code="majority_failed",
                    error_message=error_message,
                    correlation_id=correlation_id,
                    timestamp=datetime.now(UTC),
                ),
                scope=scope,
                target_user_ids=[user_id],
                correlation_id=correlation_id,
            )
            return

        await repo.update_import_status(
            import_id,
            status="ready",
            conversation_count=indexed,
            skipped_count=skipped_count,
            skipped_reasons=skipped_reasons,
        )
        parent = await repo.get_import(import_id)
        expires_at = parent["expires_at"] if parent else datetime.now(UTC)
        await event_bus.publish(
            Topics.CHATGPT_IMPORT_PARSE_DONE,
            ChatGptImportParseDoneEvent(
                import_id=import_id,
                conversation_count=indexed,
                expires_at=expires_at,
                skipped_count=skipped_count,
                skipped_reasons=skipped_reasons,
                correlation_id=correlation_id,
                timestamp=datetime.now(UTC),
            ),
            scope=scope,
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )

    except Exception as exc:
        _log.exception(
            "chatgpt_import.parse_failed",
            import_id=import_id,
        )
        await repo.update_import_status(
            import_id,
            status="failed",
            conversation_count=indexed,
            skipped_count=skipped_count,
            skipped_reasons=skipped_reasons,
            error_message=str(exc),
        )
        await event_bus.publish(
            Topics.CHATGPT_IMPORT_PARSE_FAILED,
            ChatGptImportParseFailedEvent(
                import_id=import_id,
                error_code=type(exc).__name__,
                error_message=str(exc),
                correlation_id=correlation_id,
                timestamp=datetime.now(UTC),
            ),
            scope=scope,
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )
        raise
    finally:
        # Always remove the temp file when this handler exits — even on failure.
        try:
            os.unlink(file_path)
        except OSError:
            pass
