"""Persona cloning — create a new persona that duplicates the source's
personality and technical configuration. History is never cloned.

This orchestrator is the in-process inverse of ``_import.py``:
- No archive, no manifest.
- Memory (journal + memory-bodies) is optional and all-or-nothing.
- Avatar files are duplicated via ``AvatarStore.duplicate``.
- KB attachments (``knowledge_library_ids``) are copied as references only —
  KB entities themselves are n:m and never duplicated.
- On any post-insert failure, cascade-delete the partial clone and re-raise
  as ``HTTPException(400)``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException

from backend.database import get_db
from backend.modules.persona._avatar_store import AvatarStore
from backend.modules.persona._cascade import cascade_delete_persona
from backend.modules.persona._monogram import generate_monogram
from backend.modules.persona._repository import PersonaRepository
from backend.ws.event_bus import get_event_bus
from shared.dtos.persona import PersonaDto
from shared.events.persona import PersonaCreatedEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)


async def clone_persona(
    user_id: str,
    source_id: str,
    *,
    name: str | None,
    clone_memory: bool,
) -> PersonaDto:
    correlation_id = f"persona-clone-{uuid.uuid4()}"
    repo = PersonaRepository(get_db())

    source = await repo.find_by_id(source_id, user_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Persona not found")

    final_name = (name or "").strip() or f"{source['name']} Clone"

    _log.info(
        "persona_clone.start user_id=%s correlation_id=%s source_id=%s clone_memory=%s",
        user_id, correlation_id, source_id, clone_memory,
    )

    # Generate a collision-free monogram against the user's existing set.
    existing_monograms = await repo.list_monograms_for_user(user_id)
    monogram = generate_monogram(final_name, existing_monograms)

    # Determine display_order for "append at end".
    all_personas = await repo.list_for_user(user_id)
    next_order = max((p.get("display_order", 0) for p in all_personas), default=-1) + 1

    new_id: str | None = None
    try:
        # 1. Insert the new persona with the basic fields supported by ``create``.
        #    Extended fields are applied via ``update`` afterwards — same
        #    pattern as ``_import.py``.
        new_doc = await repo.create(
            user_id=user_id,
            name=final_name,
            tagline=source.get("tagline", "") or "",
            model_unique_id=source.get("model_unique_id"),  # type: ignore[arg-type]
            system_prompt=source.get("system_prompt", "") or "",
            temperature=source.get("temperature", 1.0),
            reasoning_enabled=source.get("reasoning_enabled", False),
            nsfw=source.get("nsfw", False),
            colour_scheme=source.get("colour_scheme", "solar") or "solar",
            display_order=next_order,
            pinned=False,
            profile_image=None,  # filled after avatar duplication
            soft_cot_enabled=source.get("soft_cot_enabled", False),
            vision_fallback_model=source.get("vision_fallback_model"),
        )
        new_id = new_doc["_id"]

        # 2. Apply extended technical fields that ``create`` does not accept.
        extended: dict = {
            "monogram": monogram,
            "knowledge_library_ids": list(source.get("knowledge_library_ids") or []),
            "mcp_config": source.get("mcp_config"),
            "integrations_config": source.get("integrations_config"),
            "voice_config": source.get("voice_config"),
            "profile_crop": source.get("profile_crop"),
        }
        await repo.update(new_id, user_id, extended)

        # 3. Duplicate the avatar file (if any).
        src_avatar = source.get("profile_image")
        if src_avatar:
            store = AvatarStore()
            new_filename = store.duplicate(src_avatar)
            if new_filename is not None:
                await repo.update_profile_image(new_id, user_id, new_filename)
            else:
                _log.warning(
                    "persona_clone.avatar_missing correlation_id=%s source_avatar=%s",
                    correlation_id, src_avatar,
                )

        # 4. Memory (optional, all-or-nothing).
        if clone_memory:
            from backend.modules.memory import (
                bulk_export_for_persona,
                bulk_import_for_persona,
            )

            bundle = await bulk_export_for_persona(user_id, source_id)
            await bulk_import_for_persona(user_id, new_id, bundle)

        # 5. Re-fetch + publish PersonaCreatedEvent.
        fresh = await repo.find_by_id(new_id, user_id)
        if fresh is None:
            raise RuntimeError(f"Persona {new_id} vanished after clone")
        dto = PersonaRepository.to_dto(fresh)

        event_bus = get_event_bus()
        await event_bus.publish(
            Topics.PERSONA_CREATED,
            PersonaCreatedEvent(
                persona_id=new_id,
                user_id=user_id,
                persona=dto,
                timestamp=datetime.now(UTC),
            ),
            scope=f"persona:{new_id}",
            target_user_ids=[user_id],
        )

        _log.info(
            "persona_clone.done user_id=%s correlation_id=%s new_id=%s",
            user_id, correlation_id, new_id,
        )
        return dto

    except HTTPException:
        if new_id is not None:
            try:
                await cascade_delete_persona(user_id, new_id)
            except Exception:
                _log.exception(
                    "persona_clone.rollback_failed correlation_id=%s new_id=%s",
                    correlation_id, new_id,
                )
        raise
    except Exception as exc:
        _log.exception(
            "persona_clone.failed correlation_id=%s new_id=%s",
            correlation_id, new_id,
        )
        if new_id is not None:
            try:
                await cascade_delete_persona(user_id, new_id)
            except Exception:
                _log.exception(
                    "persona_clone.rollback_failed correlation_id=%s new_id=%s",
                    correlation_id, new_id,
                )
        raise HTTPException(
            status_code=400, detail=f"Persona clone failed: {exc}",
        ) from exc
