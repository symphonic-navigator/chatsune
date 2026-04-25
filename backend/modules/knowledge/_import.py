"""Knowledge library import — restores a ``.chatsune-knowledge.tar.gz`` archive.

Phase 3 import is the inverse of :mod:`_export`. It reuses the existing
document-upload pipeline (``_create_document_internal`` in ``_handlers``)
so that chunking + embedding trigger exactly as they would for a normal
upload — no duplicated logic, and the frontend observes each document
creation / embedding via the usual events.

Key invariants:

- **Rollback on any failure** — if any document insert (or any step after
  the library is created) raises, the orchestrator cascade-deletes the
  library (which also removes any documents + chunks already inserted)
  before re-raising.
- **Explicit allowlist** for both library and document payloads — see
  :mod:`_export` for the reasoning. Derived state (chunk_count,
  embedding_status, size_bytes, timestamps, IDs) is NEVER trusted from
  the archive.
- **Size cap** — 200 MB uncompressed. The HTTP layer enforces the
  compressed cap separately.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import tarfile
import uuid
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from backend.database import get_db
from backend.modules.knowledge._repository import KnowledgeRepository
from shared.dtos.knowledge import KnowledgeLibraryDto

_log = logging.getLogger(__name__)

# Sanity cap on uncompressed archive size. Protects against zip-bombs and
# accidental huge uploads. The HTTP layer enforces the compressed cap; this
# enforces the expanded cap while we walk the tar members.
_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024

_SUPPORTED_FORMAT = "chatsune/knowledge"
_SUPPORTED_VERSION = 1

_ALLOWED_MEDIA_TYPES = {"text/markdown", "text/plain"}


class _ImportedLibrary(BaseModel):
    """Validated shape of ``library.json``."""

    name: str = Field(min_length=1)
    description: str | None = None
    nsfw: bool = False
    default_refresh: Literal["rarely", "standard", "often"] = "standard"


class _ImportedDocument(BaseModel):
    """Validated shape of each entry in ``documents.json``."""

    title: str = Field(min_length=1)
    content: str
    media_type: str = "text/markdown"
    trigger_phrases: list[str] = Field(default_factory=list)
    refresh: Literal["rarely", "standard", "often"] | None = None


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


async def import_library_archive(
    user_id: str,
    archive_bytes: bytes,
) -> KnowledgeLibraryDto:
    """Import a knowledge-library archive for ``user_id``.

    On any error after the library is created, cascade-deletes the library
    (documents + chunks + library doc) before re-raising.
    """
    correlation_id = f"knowledge-import-{uuid.uuid4()}"

    _log.info(
        "knowledge_import.start user_id=%s correlation_id=%s size_bytes=%d",
        user_id, correlation_id, len(archive_bytes),
    )

    # --- Parse archive (before creating any persistent state) ---
    files = _extract_archive(archive_bytes)

    if "manifest.json" not in files:
        raise HTTPException(
            status_code=400, detail="Archive is missing manifest.json",
        )
    _parse_manifest(files["manifest.json"])

    if "library.json" not in files:
        raise HTTPException(
            status_code=400, detail="Archive is missing library.json",
        )
    library_raw = _parse_json_bytes(files["library.json"], "library.json")
    if not isinstance(library_raw, dict):
        raise HTTPException(
            status_code=400, detail="library.json must be an object",
        )
    try:
        library_payload = _ImportedLibrary.model_validate(library_raw)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400, detail=f"library.json is invalid: {exc}",
        ) from exc

    if "documents.json" not in files:
        raise HTTPException(
            status_code=400, detail="Archive is missing documents.json",
        )
    documents_raw = _parse_json_bytes(files["documents.json"], "documents.json")
    if not isinstance(documents_raw, list):
        raise HTTPException(
            status_code=400, detail="documents.json must be an array",
        )

    documents_payload: list[_ImportedDocument] = []
    for idx, entry in enumerate(documents_raw):
        if not isinstance(entry, dict):
            raise HTTPException(
                status_code=400,
                detail=f"documents.json[{idx}] must be an object",
            )
        try:
            doc = _ImportedDocument.model_validate(entry)
        except ValidationError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"documents.json[{idx}] is invalid: {exc}",
            ) from exc
        if doc.media_type not in _ALLOWED_MEDIA_TYPES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"documents.json[{idx}] has unsupported media_type "
                    f"'{doc.media_type}' (expected one of "
                    f"{sorted(_ALLOWED_MEDIA_TYPES)})"
                ),
            )
        documents_payload.append(doc)

    # --- Begin persisted state; wrap in rollback ---
    # Deferred import to avoid circular imports at module load.
    from backend.modules.knowledge._handlers import (
        _create_document_internal,
        _create_library_internal,
    )

    repo = KnowledgeRepository(get_db())
    library_id: str | None = None

    try:
        # 1. Create the library (publishes LIBRARY_CREATED event).
        dto, library_doc = await _create_library_internal(
            user_id=user_id,
            name=library_payload.name,
            description=library_payload.description,
            nsfw=library_payload.nsfw,
            default_refresh=library_payload.default_refresh,
            correlation_id=correlation_id,
        )
        library_id = library_doc["_id"]

        _log.info(
            "knowledge_import.library_created user_id=%s correlation_id=%s "
            "library_id=%s",
            user_id, correlation_id, library_id,
        )

        # 2. For each document, go through the normal upload pipeline so
        #    chunking + embedding + DOCUMENT_CREATED / EMBEDDING events
        #    fire exactly as they would for a hand-uploaded file.
        from backend.modules.knowledge._pti_normalisation import normalise

        for idx, doc_payload in enumerate(documents_payload):
            # Normalise defensively — old or hand-edited archives may carry
            # un-normalised phrases. _create_document_internal does not
            # normalise internally; that is the public endpoint's job.
            normalised_phrases = [
                n for n in (normalise(p) for p in doc_payload.trigger_phrases) if n
            ]
            await _create_document_internal(
                user_id=user_id,
                library_id=library_id,
                title=doc_payload.title,
                content=doc_payload.content,
                media_type=doc_payload.media_type,
                trigger_phrases=normalised_phrases,
                refresh=doc_payload.refresh,
                correlation_id=correlation_id,
            )

        _log.info(
            "knowledge_import.documents_created user_id=%s correlation_id=%s "
            "library_id=%s count=%d",
            user_id, correlation_id, library_id, len(documents_payload),
        )

        # 3. Re-fetch the library so document_count reflects the inserts.
        fresh = await repo.get_library(library_id, user_id)
        if not fresh:
            raise RuntimeError(
                f"Library {library_id} vanished after import",
            )
        fresh_dto = KnowledgeRepository.to_library_dto(fresh)

        _log.info(
            "knowledge_import.done user_id=%s correlation_id=%s library_id=%s "
            "documents=%d",
            user_id, correlation_id, library_id, fresh_dto.document_count,
        )
        return fresh_dto

    except HTTPException:
        # Known failure -> rollback + re-raise unchanged.
        if library_id is not None:
            _log.warning(
                "knowledge_import.rollback correlation_id=%s library_id=%s",
                correlation_id, library_id,
            )
            try:
                # delete_library already cascades documents + chunks.
                await repo.delete_library(library_id, user_id)
            except Exception:
                _log.exception(
                    "knowledge_import.rollback_failed correlation_id=%s "
                    "library_id=%s",
                    correlation_id, library_id,
                )
        raise
    except Exception as exc:
        _log.exception(
            "knowledge_import.failed correlation_id=%s library_id=%s",
            correlation_id, library_id,
        )
        if library_id is not None:
            try:
                await repo.delete_library(library_id, user_id)
            except Exception:
                _log.exception(
                    "knowledge_import.rollback_failed correlation_id=%s "
                    "library_id=%s",
                    correlation_id, library_id,
                )
        raise HTTPException(
            status_code=400,
            detail=f"Knowledge library import failed: {exc}",
        ) from exc
