"""Persona import orchestration — restores a ``.chatsune-persona.tar.gz`` archive.

Phase 2 import is the inverse of :mod:`_export`. It is implemented as an
orchestration of the other modules' public ``bulk_import_for_*`` APIs.

Key invariants:

- **No cross-module DB access**. All per-module state is restored via the
  public APIs of the owning module (``memory``, ``chat``, ``artefact``,
  ``storage``).
- **Rollback on any failure** — if any step after the persona is created
  raises, the orchestrator calls the persona module's own cascade-delete
  helper so no "zombie persona" is left behind with a half-populated dataset.
- **Explicit allowlist** for personality fields — ``persona.json`` carries
  only the fields that cross installs; technical config fields
  (``model_unique_id``, ``temperature``, ``reasoning_enabled``,
  ``soft_cot_enabled``, ``vision_fallback_model``, ``voice_config``,
  ``mcp_config``, ``integrations_config``, ``knowledge_library_ids``,
  ``display_order``, ``pinned``) are filled with sensible defaults on import.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import tarfile
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from backend.database import get_db
from backend.modules.persona._avatar_store import AvatarStore
from backend.modules.persona._monogram import generate_monogram
from backend.modules.persona._repository import PersonaRepository
from backend.ws.event_bus import get_event_bus
from shared.dtos.export import (
    ArtefactsBundleDto,
    MemoryBundleDto,
    SessionsBundleDto,
    StorageBundleDto,
)
from shared.dtos.persona import PersonaDto
from shared.events.persona import PersonaCreatedEvent
from shared.topics import Topics

_log = logging.getLogger(__name__)

# Sanity cap on uncompressed archive size. Protects against zip-bombs and
# accidental 4 GB uploads. The HTTP layer enforces the compressed cap; this
# enforces the expanded cap while we walk the tar members.
_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024

_SUPPORTED_FORMAT = "chatsune/persona"
_SUPPORTED_VERSION = 1

# Allowlisted personality fields — mirrors the export side.
_PERSONALITY_STR_FIELDS: tuple[str, ...] = (
    "name",
    "tagline",
    "system_prompt",
    "colour_scheme",
    "monogram",
)

# Map avatar file extension back to media type.
_EXT_TO_MEDIA_TYPE: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}


def _extract_archive(archive_bytes: bytes) -> dict[str, bytes]:
    """Return ``{path: bytes}`` for every regular file in the archive.

    Enforces a 200 MB uncompressed cap by aborting as soon as the running
    total is exceeded.
    """
    try:
        gz = gzip.GzipFile(fileobj=io.BytesIO(archive_bytes), mode="rb")
        tar = tarfile.open(fileobj=gz, mode="r")
    except (OSError, tarfile.TarError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Archive is not a valid .tar.gz file: {exc}",
        ) from exc

    files: dict[str, bytes] = {}
    running_total = 0
    try:
        for member in tar:
            if not member.isfile():
                continue
            size = member.size
            running_total += size
            if running_total > _MAX_UNCOMPRESSED_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Archive exceeds 200 MB uncompressed limit",
                )
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            files[member.name] = extracted.read()
    finally:
        tar.close()
        gz.close()

    return files


def _parse_manifest(raw: bytes) -> dict[str, Any]:
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"manifest.json is not valid JSON: {exc}",
        ) from exc
    if not isinstance(manifest, dict):
        raise HTTPException(status_code=400, detail="manifest.json must be an object")
    if manifest.get("format") != _SUPPORTED_FORMAT:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported archive format '{manifest.get('format')}' "
                f"(expected '{_SUPPORTED_FORMAT}')"
            ),
        )
    if manifest.get("version") != _SUPPORTED_VERSION:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported archive version {manifest.get('version')!r} "
                f"(expected {_SUPPORTED_VERSION})"
            ),
        )
    return manifest


def _parse_json_bytes(raw: bytes, where: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"{where} is not valid JSON: {exc}",
        ) from exc


def _find_avatar(files: dict[str, bytes]) -> tuple[bytes, str] | None:
    """Return ``(avatar_bytes, extension)`` for the first ``profile_image.*`` file."""
    for name, data in files.items():
        if name.startswith("profile_image."):
            ext = name.rsplit(".", 1)[-1].lower()
            return data, ext
    return None


async def import_persona_archive(
    user_id: str,
    archive_bytes: bytes,
) -> PersonaDto:
    """Import a persona archive for ``user_id``.

    On any error after the persona document is inserted, the orchestrator
    cascade-deletes everything it may have written (chat sessions, artefacts,
    memory, storage blobs, avatar file, the persona doc itself) before
    re-raising.
    """
    correlation_id = f"persona-import-{uuid.uuid4()}"

    _log.info(
        "persona_import.start user_id=%s correlation_id=%s size_bytes=%d",
        user_id, correlation_id, len(archive_bytes),
    )

    # --- Parse archive (before creating any persistent state) ---
    files = _extract_archive(archive_bytes)

    if "manifest.json" not in files:
        raise HTTPException(
            status_code=400, detail="Archive is missing manifest.json",
        )
    manifest = _parse_manifest(files["manifest.json"])

    if "persona.json" not in files:
        raise HTTPException(
            status_code=400, detail="Archive is missing persona.json",
        )
    personality = _parse_json_bytes(files["persona.json"], "persona.json")
    if not isinstance(personality, dict):
        raise HTTPException(
            status_code=400, detail="persona.json must be an object",
        )

    name = personality.get("name")
    if not isinstance(name, str) or not name.strip():
        raise HTTPException(
            status_code=400,
            detail="persona.json is missing a non-empty 'name' field",
        )

    include_content = bool(manifest.get("include_content", False))

    # sessions.json is always present.
    if "sessions.json" not in files:
        raise HTTPException(
            status_code=400, detail="Archive is missing sessions.json",
        )
    try:
        sessions_bundle = SessionsBundleDto.model_validate(
            _parse_json_bytes(files["sessions.json"], "sessions.json"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"sessions.json is invalid: {exc}",
        ) from exc

    memory_bundle: MemoryBundleDto | None = None
    artefacts_bundle: ArtefactsBundleDto | None = None
    storage_bundle: StorageBundleDto | None = None
    storage_blobs: dict[str, bytes] = {}
    if include_content:
        try:
            memory_bundle = MemoryBundleDto.model_validate(
                _parse_json_bytes(files.get("memory.json", b"{}"), "memory.json"),
            )
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"memory.json is invalid: {exc}",
            ) from exc
        try:
            artefacts_bundle = ArtefactsBundleDto.model_validate(
                _parse_json_bytes(
                    files.get("artefacts.json", b"{}"), "artefacts.json",
                ),
            )
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"artefacts.json is invalid: {exc}",
            ) from exc
        storage_manifest_bytes = files.get("storage/manifest.json")
        if storage_manifest_bytes is None:
            storage_bundle = StorageBundleDto(files=[])
        else:
            try:
                storage_bundle = StorageBundleDto.model_validate(
                    _parse_json_bytes(
                        storage_manifest_bytes, "storage/manifest.json",
                    ),
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"storage/manifest.json is invalid: {exc}",
                ) from exc
        # Collect blobs: walk storage/files/*.bin
        for path, data in files.items():
            if path.startswith("storage/files/") and path.endswith(".bin"):
                export_id = path[len("storage/files/"):-len(".bin")]
                storage_blobs[export_id] = data

    # --- Begin persisted state; wrap in rollback ---
    from backend.modules.persona._cascade import cascade_delete_persona

    persona_id: str | None = None
    repo = PersonaRepository(get_db())

    try:
        # 1. Create persona with defaults for excluded technical fields.
        existing_monograms = await repo.list_monograms_for_user(user_id)
        # Prefer imported monogram if it doesn't clash; otherwise regenerate.
        imported_monogram = personality.get("monogram")
        if (
            isinstance(imported_monogram, str)
            and imported_monogram
            and imported_monogram not in existing_monograms
        ):
            monogram = imported_monogram
        else:
            monogram = generate_monogram(name, existing_monograms)

        persona_doc = await repo.create(
            user_id=user_id,
            name=name,
            tagline=personality.get("tagline", "") or "",
            # Excluded technical config — defaults from CreatePersonaDto.
            model_unique_id=None,  # type: ignore[arg-type]  # field is str in repo but nullable in DB/DTO
            system_prompt=personality.get("system_prompt", "") or "",
            temperature=1.0,
            reasoning_enabled=False,
            nsfw=bool(personality.get("nsfw", False)),
            use_memory=bool(personality.get("use_memory", True)),
            colour_scheme=personality.get("colour_scheme", "solar") or "solar",
            display_order=0,
            pinned=False,
            profile_image=None,
            soft_cot_enabled=False,
            vision_fallback_model=None,
        )
        persona_id = persona_doc["_id"]
        await repo.update(persona_id, user_id, {"monogram": monogram})
        persona_doc["monogram"] = monogram

        # Restore profile_crop if present.
        crop = personality.get("profile_crop")
        if isinstance(crop, dict):
            await repo.update_profile_crop(persona_id, user_id, crop)

        _log.info(
            "persona_import.persona_created user_id=%s correlation_id=%s persona_id=%s",
            user_id, correlation_id, persona_id,
        )

        # 2. Avatar (optional).
        if personality.get("has_avatar"):
            avatar = _find_avatar(files)
            if avatar is not None:
                avatar_bytes, ext = avatar
                if ext not in _EXT_TO_MEDIA_TYPE:
                    _log.warning(
                        "persona_import.avatar_unknown_ext correlation_id=%s ext=%s",
                        correlation_id, ext,
                    )
                else:
                    store = AvatarStore()
                    filename = store.save(avatar_bytes, ext)
                    await repo.update_profile_image(persona_id, user_id, filename)

        # 3. Sessions — deferred import to keep module boundaries clean.
        from backend.modules.chat import (
            bulk_import_for_persona as chat_import,
        )

        session_id_map = await chat_import(user_id, persona_id, sessions_bundle)
        _log.info(
            "persona_import.sessions_imported correlation_id=%s persona_id=%s count=%d",
            correlation_id, persona_id, len(session_id_map),
        )

        # 4. Content bundles (optional).
        if include_content:
            from backend.modules.artefact import (
                bulk_import_for_sessions as artefact_import,
            )
            from backend.modules.memory import (
                bulk_import_for_persona as memory_import,
            )
            from backend.modules.storage import (
                bulk_import_for_persona as storage_import,
            )

            assert memory_bundle is not None
            assert artefacts_bundle is not None
            assert storage_bundle is not None

            await memory_import(user_id, persona_id, memory_bundle)
            await artefact_import(user_id, session_id_map, artefacts_bundle)
            await storage_import(
                user_id, persona_id, storage_bundle, storage_blobs,
            )
            _log.info(
                "persona_import.content_imported correlation_id=%s persona_id=%s "
                "memory_entries=%d memory_bodies=%d artefacts=%d storage_files=%d",
                correlation_id, persona_id,
                len(memory_bundle.journal_entries),
                len(memory_bundle.memory_bodies),
                len(artefacts_bundle.artefacts),
                len(storage_bundle.files),
            )

        # 5. Re-fetch + publish PersonaCreatedEvent.
        fresh = await repo.find_by_id(persona_id, user_id)
        if not fresh:
            raise RuntimeError(
                f"Persona {persona_id} vanished after import",
            )
        dto = PersonaRepository.to_dto(fresh)

        event_bus = get_event_bus()
        await event_bus.publish(
            Topics.PERSONA_CREATED,
            PersonaCreatedEvent(
                persona_id=persona_id,
                user_id=user_id,
                persona=dto,
                timestamp=datetime.now(timezone.utc),
            ),
            scope=f"persona:{persona_id}",
            target_user_ids=[user_id],
        )

        _log.info(
            "persona_import.done user_id=%s correlation_id=%s persona_id=%s",
            user_id, correlation_id, persona_id,
        )
        return dto

    except HTTPException:
        # Known failure -> rollback + re-raise unchanged.
        if persona_id is not None:
            _log.warning(
                "persona_import.rollback correlation_id=%s persona_id=%s",
                correlation_id, persona_id,
            )
            try:
                await cascade_delete_persona(user_id, persona_id)
            except Exception:
                _log.exception(
                    "persona_import.rollback_failed correlation_id=%s persona_id=%s",
                    correlation_id, persona_id,
                )
        raise
    except Exception as exc:
        _log.exception(
            "persona_import.failed correlation_id=%s persona_id=%s",
            correlation_id, persona_id,
        )
        if persona_id is not None:
            try:
                await cascade_delete_persona(user_id, persona_id)
            except Exception:
                _log.exception(
                    "persona_import.rollback_failed correlation_id=%s persona_id=%s",
                    correlation_id, persona_id,
                )
        raise HTTPException(
            status_code=400,
            detail=f"Persona import failed: {exc}",
        ) from exc
