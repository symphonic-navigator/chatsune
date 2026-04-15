"""Persona export/import bundle DTOs — internal orchestration contracts.

These DTOs are returned from each module's ``bulk_export_for_persona`` (or
equivalent) and consumed by ``bulk_import_for_persona`` / sibling import
methods. They are internal orchestration contracts — they are NOT sent to the
frontend directly. Phase 2 of the persona import/export feature packages
them into a tar.gz archive and exposes HTTP endpoints.

Design notes:

- Documents are represented as plain ``dict`` payloads so each module can
  preserve arbitrary per-collection fields without a schema change requiring
  updates here. The orchestrator only cares about stripped owner-identifiers
  (``_id`` / ``user_id`` / ``persona_id`` / ``session_id``) and a few
  explicit cross-reference fields (``original_id``).
- Binaries are kept out-of-band: ``StorageBundleDto`` carries only metadata,
  and bytes are passed alongside as a ``dict[export_id, bytes]`` so the
  Phase 2 archiver can stream them directly into the tar.
"""

from datetime import datetime

from pydantic import BaseModel


class MemoryBundleDto(BaseModel):
    """Memory module export: journal entries + consolidated memory bodies.

    Each dict has had ``_id``, ``user_id`` and ``persona_id`` stripped.
    Timestamps (``created_at``, ``committed_at``), ``state``, ``version``,
    etc., are preserved unchanged.
    """

    journal_entries: list[dict]
    memory_bodies: list[dict]


class SessionExportDto(BaseModel):
    """A single chat session with its messages, ready for export.

    ``original_id`` is intentionally kept (outside ``session_fields``) so the
    orchestrator can build an ``old_session_id -> new_session_id`` mapping to
    remap artefact session references on import. It is NOT the new id on
    import; bulk_import assigns a fresh UUID.

    ``session_fields`` is an explicit-allowlist dict (not a full model_dump)
    so that any future fields added to the chat session document (e.g.
    ``project_id``) are automatically excluded unless explicitly added.
    """

    original_id: str
    session_fields: dict
    messages: list[dict]


class SessionsBundleDto(BaseModel):
    sessions: list[SessionExportDto]


class ArtefactExportDto(BaseModel):
    """A single artefact with its version history.

    ``original_session_id`` is the OLD session id — it is remapped to the
    newly-created session id during import via the
    ``old_session_id -> new_session_id`` mapping returned from the chat
    module's bulk_import.
    """

    original_session_id: str
    artefact_fields: dict
    versions: list[dict]


class ArtefactsBundleDto(BaseModel):
    artefacts: list[ArtefactExportDto]


class StorageFileRecordDto(BaseModel):
    """Metadata for a single storage file in an export bundle.

    Binary content is carried separately as ``dict[export_id, bytes]`` so the
    Phase 2 packager can stream bytes directly into the archive. ``export_id``
    is a fresh UUID assigned at export time so it doubles as the archive
    filename; on import a new storage-side UUID is generated.
    """

    export_id: str
    original_name: str
    display_name: str
    media_type: str
    size_bytes: int
    thumbnail_b64: str | None = None
    text_preview: str | None = None
    vision_descriptions: dict[str, dict] | None = None
    created_at: datetime
    updated_at: datetime


class StorageBundleDto(BaseModel):
    files: list[StorageFileRecordDto]
