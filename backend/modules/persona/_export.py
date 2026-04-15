"""Persona export orchestration — builds a ``.chatsune-persona.tar.gz`` archive.

Package layout inside the archive::

    manifest.json                  # required first file
    persona.json                   # personality (explicit allowlist — see below)
    profile_image.<ext>            # optional, avatar binary
    sessions.json                  # chat history — always included
    # --- only when include_content=true in the manifest ---
    memory.json                    # journal entries + memory bodies
    artefacts.json                 # artefacts + their version history
    storage/manifest.json          # file metadata (StorageBundleDto as JSON)
    storage/files/<export_id>.bin  # raw bytes per file

The personality export is an **explicit allowlist** (see ``_PERSONALITY_FIELDS``)
— NOT a dump of the persona document. Technical config (model_unique_id,
temperature, reasoning_enabled, etc.) and assignments (knowledge_library_ids,
display_order, pinned) are intentionally excluded so that a persona can be
shared between users / installs without carrying system-specific references.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import re
import tarfile
from datetime import UTC, datetime

from fastapi import HTTPException

from backend.database import get_db
from backend.modules.persona._avatar_store import AvatarStore
from backend.modules.persona._repository import PersonaRepository

_log = logging.getLogger(__name__)


# Explicit allowlist of personality fields that cross persona boundaries.
# INTENTIONALLY NOT a ``model_dump()`` of the whole doc — see module docstring.
_PERSONALITY_FIELDS: tuple[str, ...] = (
    "name",
    "tagline",
    "system_prompt",
    "nsfw",
    "colour_scheme",
    "monogram",
    # profile_crop is serialised as a plain dict, has_avatar is a bool flag.
)


# Extension lookup from media_type — mirrors _handlers._ALLOWED_IMAGE_TYPES but
# kept local to avoid importing from the handler module (keeps _export.py
# loadable without the handler's dependencies).
_MEDIA_TYPE_TO_EXT: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}

# Fallback when the stored avatar has no known content-type — infer from
# filename extension already used by AvatarStore.
_EXT_TO_MEDIA_TYPE: dict[str, str] = {v: k for k, v in _MEDIA_TYPE_TO_EXT.items()}


def _slug(name: str) -> str:
    """Return a filesystem-safe slug for the persona name."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", name or "persona").strip("-").lower()
    return s or "persona"


def _tar_add_bytes(tar: tarfile.TarFile, name: str, data: bytes, mtime: float) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = int(mtime)
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(data))


async def export_persona_archive(
    user_id: str,
    persona_id: str,
    include_content: bool,
) -> tuple[bytes, str]:
    """Build and return ``(gzip_bytes, suggested_filename)``.

    Raises ``HTTPException(404)`` if the persona doesn't exist or isn't owned
    by ``user_id``.
    """
    # Deferred imports — other modules depend on event_bus / DB / etc. at
    # runtime; importing here keeps the module boundary clean and avoids
    # circular-import headaches at startup.
    from backend.modules.chat import bulk_export_for_persona as chat_export

    _log.info(
        "persona_export.start user_id=%s persona_id=%s include_content=%s",
        user_id, persona_id, include_content,
    )

    repo = PersonaRepository(get_db())
    persona = await repo.find_by_id(persona_id, user_id)
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    now = datetime.now(UTC)

    # --- Personality (a) ---
    # Build via explicit allowlist. Technical config is intentionally excluded.
    personality: dict = {
        field: persona.get(field) for field in _PERSONALITY_FIELDS
    }
    personality["profile_crop"] = persona.get("profile_crop")
    has_avatar = bool(persona.get("profile_image"))
    personality["has_avatar"] = has_avatar

    # --- Avatar bytes ---
    avatar_bytes: bytes | None = None
    avatar_ext: str | None = None
    if has_avatar:
        store = AvatarStore()
        filename = persona["profile_image"]
        avatar_bytes = store.load(filename)
        if avatar_bytes is None:
            # Best-effort: DB says avatar exists but the blob is gone.
            _log.warning(
                "persona_export.missing_avatar user_id=%s persona_id=%s filename=%s",
                user_id, persona_id, filename,
            )
            personality["has_avatar"] = False
            has_avatar = False
        else:
            ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
            avatar_ext = ext

    # --- Sessions (a — chat history is part of personality) ---
    sessions_bundle = await chat_export(user_id, persona_id)
    session_ids = [s.original_id for s in sessions_bundle.sessions]

    # --- Content bundles (b) ---
    memory_bundle = None
    artefacts_bundle = None
    storage_bundle = None
    storage_blobs: dict[str, bytes] = {}
    if include_content:
        from backend.modules.artefact import bulk_export_for_sessions as artefact_export
        from backend.modules.memory import bulk_export_for_persona as memory_export
        from backend.modules.storage import bulk_export_for_persona as storage_export

        memory_bundle = await memory_export(user_id, persona_id)
        artefacts_bundle = await artefact_export(user_id, session_ids)
        storage_bundle, storage_blobs = await storage_export(user_id, persona_id)

    # --- Manifest ---
    manifest = {
        "format": "chatsune/persona",
        "version": 1,
        "exported_at": now.isoformat().replace("+00:00", "Z"),
        "include_content": include_content,
        "source_persona_name": persona.get("name", ""),
    }

    # --- Build tar.gz ---
    buf = io.BytesIO()
    mtime = now.timestamp()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=int(mtime)) as gz:
        with tarfile.open(fileobj=gz, mode="w") as tar:  # type: ignore[arg-type]
            _tar_add_bytes(
                tar, "manifest.json",
                json.dumps(manifest, indent=2).encode("utf-8"),
                mtime,
            )
            _tar_add_bytes(
                tar, "persona.json",
                json.dumps(personality, indent=2, default=str).encode("utf-8"),
                mtime,
            )
            if has_avatar and avatar_bytes is not None:
                _tar_add_bytes(
                    tar, f"profile_image.{avatar_ext}",
                    avatar_bytes,
                    mtime,
                )
            _tar_add_bytes(
                tar, "sessions.json",
                json.dumps(
                    sessions_bundle.model_dump(mode="json"),
                    indent=2,
                ).encode("utf-8"),
                mtime,
            )
            if include_content:
                assert memory_bundle is not None
                assert artefacts_bundle is not None
                assert storage_bundle is not None
                _tar_add_bytes(
                    tar, "memory.json",
                    json.dumps(
                        memory_bundle.model_dump(mode="json"),
                        indent=2,
                    ).encode("utf-8"),
                    mtime,
                )
                _tar_add_bytes(
                    tar, "artefacts.json",
                    json.dumps(
                        artefacts_bundle.model_dump(mode="json"),
                        indent=2,
                    ).encode("utf-8"),
                    mtime,
                )
                _tar_add_bytes(
                    tar, "storage/manifest.json",
                    json.dumps(
                        storage_bundle.model_dump(mode="json"),
                        indent=2,
                    ).encode("utf-8"),
                    mtime,
                )
                for export_id, data in storage_blobs.items():
                    _tar_add_bytes(
                        tar, f"storage/files/{export_id}.bin",
                        data,
                        mtime,
                    )

    archive_bytes = buf.getvalue()

    name_slug = _slug(persona.get("name", ""))
    date_slug = now.strftime("%Y%m%d")
    filename = f"persona-{name_slug}-{date_slug}.chatsune-persona.tar.gz"

    _log.info(
        "persona_export.done user_id=%s persona_id=%s bytes=%d sessions=%d include_content=%s",
        user_id, persona_id, len(archive_bytes),
        len(sessions_bundle.sessions), include_content,
    )

    return archive_bytes, filename
