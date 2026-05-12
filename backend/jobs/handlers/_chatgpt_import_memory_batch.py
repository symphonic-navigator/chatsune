"""Batch memory-extraction handler for ChatGPT-imported sessions.

Drives the ``extract_and_store_messages`` core function once per
imported session, in chronological order, with explicit pause semantics
on terminal failure. See
``devdocs/specs/2026-05-12-imported-conversation-memory-extract-design.md``
for the architectural rationale.

State invariants the handler relies on:

* The batch row exists with ``state="running"`` — claimed atomically by
  the per-conversation trigger handler or by the Resume endpoint.
* ``session_ids`` is sorted oldest-first by original ChatGPT
  ``create_time``.
* The in-flight slot
  (:func:`backend.jobs._dedup.memory_extraction_slot_key`) is free or
  held by us; the slot serialises against live-flow memory extraction
  for the same persona.

Failure model: any terminal exception inside the per-session loop
transitions the row to ``paused`` with a structured ``reason`` and
publishes :class:`ChatGptImportMemoryPausedEvent`. The slot's TTL is
extended to seven days so live-flow extraction stays gated until the
user takes action; the slot expires as a safety net if the user never
returns.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog

from backend.database import get_db
from backend.jobs._dedup import (
    memory_extraction_slot_key,
    release_inflight_slot,
    try_acquire_inflight_slot,
)
from backend.jobs._errors import ProviderUnavailableError, UnrecoverableJobError
from backend.jobs._models import JobConfig, JobEntry
from backend.modules.chatgpt_import._memory_batch_repository import (
    ChatGptImportMemoryBatchRepository,
)
from shared.events.chatgpt_import import (
    ChatGptImportMemoryBatchDoneEvent,
    ChatGptImportMemoryPausedEvent,
    ChatGptImportMemoryProgressEvent,
)
from shared.topics import Topics

_log = structlog.get_logger(__name__)

# Slot TTL while we are actively processing — refreshed after every
# session so a long batch keeps the lock alive. One hour gives plenty of
# headroom for a single session's extraction even on a slow upstream.
_SLOT_RUNNING_TTL_SECONDS = 3600

# TTL applied while the batch is paused: the slot stays held so the live
# flow does not start writing memory entries out of order with respect
# to the unprocessed imported sessions. Seven days is long enough for the
# user to notice and react; if they truly abandon the batch, the slot
# expires as a safety net.
_SLOT_PAUSED_TTL_SECONDS = 7 * 24 * 3600

# Per-LLM-call message chunk size. Matches the live-flow default; the
# batch can process arbitrarily many messages by looping until
# ``list_unextracted_user_messages`` returns nothing.
_MESSAGES_PER_CHUNK = 20


async def handle_chatgpt_import_memory_batch(
    job: JobEntry,
    config: JobConfig,
    redis,
    event_bus,
) -> None:
    payload = job.payload
    import_id: str = payload["import_id"]
    persona_id: str = payload["persona_id"]
    force_budget: bool = bool(payload.get("force_budget", False))
    user_id = job.user_id
    correlation_id = job.correlation_id

    # Deferred imports to keep the module-load graph stable and break
    # potential cycles (chat → memory → chat). See _extraction_core.py.
    from backend.modules.chat import (
        get_session_summaries,
        list_unextracted_messages_for_session,
    )
    from backend.modules.memory import extract_and_store_messages

    db = get_db()
    batch_repo = ChatGptImportMemoryBatchRepository(db)

    batch = await batch_repo.get(import_id, persona_id)
    if batch is None:
        _log.warning(
            "chatgpt_import.memory.batch.missing",
            import_id=import_id,
            persona_id=persona_id,
        )
        return
    if batch["state"] != "running":
        _log.warning(
            "chatgpt_import.memory.batch.not_running",
            import_id=import_id,
            persona_id=persona_id,
            state=batch["state"],
        )
        return

    session_ids: list[str] = list(batch.get("session_ids") or [])
    total = len(session_ids)
    model_unique_id: str = batch["model_unique_id"]
    scope_import = f"chatgpt_import:{import_id}"
    scope_persona = f"persona:{persona_id}"

    slot_key = memory_extraction_slot_key(user_id, persona_id)
    # Track the terminal state so the finally block can adjust the slot
    # TTL correctly: done/discarded → release; paused → 7-day hold.
    final_state: str = "running"

    async def _publish_paused(
        *,
        session_index: int,
        session_id: str,
        reason: str,
        user_message: str,
        detail: str | None,
    ) -> None:
        await batch_repo.mark_paused(
            import_id=import_id,
            persona_id=persona_id,
            session_index=session_index,
            session_id=session_id,
            reason=reason,
            user_message=user_message,
            detail=detail,
        )
        event = ChatGptImportMemoryPausedEvent(
            import_id=import_id,
            persona_id=persona_id,
            paused_at_session_index=session_index,
            paused_at_session_id=session_id,
            total=total,
            reason=reason,  # type: ignore[arg-type]
            user_message=user_message,
            detail=detail,
            correlation_id=correlation_id,
            timestamp=datetime.now(UTC),
        )
        # Match the existing per-import events: publish on both scopes
        # so the import-detail tab and any persona-bound UI react.
        for scope in (scope_import, scope_persona):
            await event_bus.publish(
                Topics.CHATGPT_IMPORT_MEMORY_PAUSED,
                event,
                scope=scope,
                target_user_ids=[user_id],
                correlation_id=correlation_id,
            )

    async def _publish_progress(
        *,
        session_index: int,
        session_id: str,
        session_title: str,
        state: str,
        entries_created: int | None,
    ) -> None:
        event = ChatGptImportMemoryProgressEvent(
            import_id=import_id,
            persona_id=persona_id,
            session_id=session_id,
            session_title=session_title,
            session_index=session_index,
            total=total,
            state=state,  # type: ignore[arg-type]
            entries_created=entries_created,
            correlation_id=correlation_id,
            timestamp=datetime.now(UTC),
        )
        for scope in (scope_import, scope_persona):
            await event_bus.publish(
                Topics.CHATGPT_IMPORT_MEMORY_PROGRESS,
                event,
                scope=scope,
                target_user_ids=[user_id],
                correlation_id=correlation_id,
            )

    try:
        # Acquire the per-persona memory-extraction slot. If someone
        # else holds it (e.g. an earlier live-flow extraction that is
        # still in flight), pause without progress so the user can
        # Resume in a moment.
        slot_acquired = await try_acquire_inflight_slot(
            redis, slot_key, ttl_seconds=_SLOT_RUNNING_TTL_SECONDS,
        )
        if not slot_acquired:
            await _publish_paused(
                session_index=1,
                session_id=session_ids[0] if session_ids else "",
                reason="other",
                user_message=(
                    "Memory extraction is busy for this persona — "
                    "click Resume in a moment."
                ),
                detail="memory_extraction_slot_busy",
            )
            final_state = "paused"
            return

        # Resolve session titles in bulk so progress events carry a
        # readable label. Deleted sessions simply do not appear in the
        # returned map; we tolerate the gap by skipping below.
        titles_by_id: dict[str, str] = {}
        if session_ids:
            summaries = await get_session_summaries(session_ids, user_id)
            titles_by_id = {
                sid: (summary.get("title") or "")
                for sid, summary in summaries.items()
            }

        for index, session_id in enumerate(session_ids, start=1):
            # Tolerate sessions the user deleted between submit and now.
            if session_id not in titles_by_id:
                _log.info(
                    "chatgpt_import.memory.batch.session_skipped",
                    import_id=import_id,
                    persona_id=persona_id,
                    session_id=session_id,
                    reason="session_not_found",
                )
                continue

            session_title = titles_by_id[session_id]

            await _publish_progress(
                session_index=index,
                session_id=session_id,
                session_title=session_title,
                state="extracting",
                entries_created=None,
            )

            session_entries_total = 0
            # Inner loop: keep pulling unextracted messages until the
            # session is fully drained. Each iteration handles a chunk
            # of ``_MESSAGES_PER_CHUNK`` via the extraction core.
            while True:
                unextracted = await list_unextracted_messages_for_session(
                    session_id, limit=_MESSAGES_PER_CHUNK,
                )
                if not unextracted:
                    break

                msg_ids = [str(m["_id"]) for m in unextracted]
                msg_contents = [m.get("content", "") for m in unextracted]
                try:
                    result = await extract_and_store_messages(
                        user_id=user_id,
                        persona_id=persona_id,
                        session_id=session_id,
                        model_unique_id=model_unique_id,
                        messages=msg_contents,
                        message_ids=msg_ids,
                        correlation_id=correlation_id,
                        redis=redis,
                        db=db,
                        event_bus=event_bus,
                        skip_budget_reserve=force_budget,
                    )
                except ProviderUnavailableError as exc:
                    await _publish_paused(
                        session_index=index,
                        session_id=session_id,
                        reason="provider_unavailable",
                        user_message=(
                            "Provider not reachable. Try Resume "
                            "once the connection is back."
                        ),
                        detail=str(exc)[:200],
                    )
                    final_state = "paused"
                    return
                except UnrecoverableJobError as exc:
                    # Today ``check_and_reserve_budget`` is the only
                    # path that raises ``UnrecoverableJobError`` from
                    # inside the extraction core. Treat it as a budget
                    # pause so the UI can offer the force-budget Resume
                    # variant — same reasoning the spec lays out in
                    # §5.1 (failure taxonomy).
                    await _publish_paused(
                        session_index=index,
                        session_id=session_id,
                        reason="budget_exhausted",
                        user_message=(
                            "Daily budget exhausted. Resume tomorrow "
                            "or use 'Resume now — exceed budget'."
                        ),
                        detail=str(exc)[:200],
                    )
                    final_state = "paused"
                    return
                except asyncio.CancelledError:
                    # The job consumer's execution timeout cancelled
                    # us mid-call. The slot's TTL extension happens in
                    # the finally block via final_state="paused" if we
                    # already wrote that, but here we have not — so do
                    # not transition the row, just let the cancel
                    # propagate. The row stays in ``running`` and a
                    # subsequent Resume picks up where we left off
                    # because ``list_unextracted_user_messages``
                    # filters by ``extracted_at``.
                    raise
                except Exception as exc:  # noqa: BLE001
                    _log.exception(
                        "chatgpt_import.memory.batch.session_error",
                        import_id=import_id,
                        persona_id=persona_id,
                        session_id=session_id,
                    )
                    await _publish_paused(
                        session_index=index,
                        session_id=session_id,
                        reason="other",
                        user_message=(
                            f"Memory extraction failed: {exc!s}"[:200]
                        ),
                        detail=type(exc).__name__,
                    )
                    final_state = "paused"
                    return

                session_entries_total += result.entries_created
                await batch_repo.add_entries_created(
                    import_id, persona_id, result.entries_created,
                )

            # Refresh the slot's TTL after every drained session so a
            # long batch does not let the safety-net TTL fire.
            try:
                await redis.expire(slot_key, _SLOT_RUNNING_TTL_SECONDS)
            except Exception:
                _log.exception(
                    "chatgpt_import.memory.batch.slot_refresh_failed",
                    slot_key=slot_key,
                )

            await _publish_progress(
                session_index=index,
                session_id=session_id,
                session_title=session_title,
                state="done",
                entries_created=session_entries_total,
            )

        # All sessions drained — terminal success.
        await batch_repo.mark_done(import_id, persona_id)
        final_state = "done"

        # Re-read to surface the authoritative total in the done event.
        finished = await batch_repo.get(import_id, persona_id)
        total_entries_created = (
            int(finished.get("total_entries_created", 0)) if finished else 0
        )
        done_event = ChatGptImportMemoryBatchDoneEvent(
            import_id=import_id,
            persona_id=persona_id,
            total=total,
            total_entries_created=total_entries_created,
            correlation_id=correlation_id,
            timestamp=datetime.now(UTC),
        )
        for scope in (scope_import, scope_persona):
            await event_bus.publish(
                Topics.CHATGPT_IMPORT_MEMORY_DONE,
                done_event,
                scope=scope,
                target_user_ids=[user_id],
                correlation_id=correlation_id,
            )

    finally:
        # Adjust the slot lifecycle based on what we ended on. Done/
        # discarded → release so live-flow extraction can resume.
        # Paused → 7-day TTL hold (see _SLOT_PAUSED_TTL_SECONDS). Other
        # branches (e.g. an early return because the row was missing)
        # leave the slot alone since we never acquired it.
        if final_state in ("done", "discarded"):
            try:
                await release_inflight_slot(redis, slot_key)
            except Exception:
                _log.exception(
                    "chatgpt_import.memory.batch.slot_release_failed",
                    slot_key=slot_key,
                )
        elif final_state == "paused":
            try:
                await redis.expire(slot_key, _SLOT_PAUSED_TTL_SECONDS)
            except Exception:
                _log.exception(
                    "chatgpt_import.memory.batch.slot_extend_failed",
                    slot_key=slot_key,
                )
