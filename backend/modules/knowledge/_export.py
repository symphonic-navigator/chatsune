"""Knowledge library export — builds a ``.chatsune-knowledge.tar.gz`` archive.

Package layout inside the archive::

    manifest.json       # {format, version, exported_at, source_library_name}
    library.json        # {name, description, nsfw}
    documents.json      # [{title, content, media_type}, ...]

All document content is inlined — it's just markdown / plain text. Chunks
and embeddings are NOT exported; they are derivable and get regenerated
via the normal document-upload pipeline on import.

Document serialisation uses an **explicit allowlist** (``_DOCUMENT_FIELDS``):
we ship the portable "what the user typed" fields (``title``, ``content``,
``media_type``) and intentionally drop derived state (``size_bytes``,
``chunk_count``, ``embedding_status``, ``embedding_error``, ``retry_count``,
timestamps, IDs) so that imports into other installs start from a clean
slate rather than carrying stale references.
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
from backend.modules.knowledge._repository import KnowledgeRepository

_log = logging.getLogger(__name__)


# Explicit allowlist of document fields. INTENTIONALLY NOT a ``model_dump()``
# of the whole doc — see module docstring for the reasoning.
_DOCUMENT_FIELDS: tuple[str, ...] = ("title", "content", "media_type")

# Explicit allowlist of library fields that cross installs.
_LIBRARY_FIELDS: tuple[str, ...] = ("name", "description", "nsfw")


def _slug(name: str) -> str:
    """Return a filesystem-safe slug for the library name."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", name or "library").strip("-").lower()
    return s or "library"


def _tar_add_bytes(tar: tarfile.TarFile, name: str, data: bytes, mtime: float) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mtime = int(mtime)
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(data))


async def export_library_archive(
    user_id: str,
    library_id: str,
) -> tuple[bytes, str]:
    """Build and return ``(gzip_bytes, suggested_filename)``.

    Raises ``HTTPException(404)`` if the library doesn't exist or isn't
    owned by ``user_id``.
    """
    _log.info(
        "knowledge_export.start user_id=%s library_id=%s",
        user_id, library_id,
    )

    repo = KnowledgeRepository(get_db())
    library = await repo.get_library(library_id, user_id)
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")

    # list_documents excludes the ``content`` field (it's a list view). Re-fetch
    # each document via get_document to include content. For large libraries
    # this could be optimised to a single find() with content included, but
    # for now the N+1 is acceptable and keeps us on the public repo API.
    doc_list_stubs = await repo.list_documents(library_id, user_id)
    documents: list[dict] = []
    for stub in doc_list_stubs:
        full = await repo.get_document(stub["_id"], user_id)
        if not full:
            continue
        documents.append(
            {field: full.get(field) for field in _DOCUMENT_FIELDS}
        )

    library_payload = {field: library.get(field) for field in _LIBRARY_FIELDS}

    now = datetime.now(UTC)
    manifest = {
        "format": "chatsune/knowledge",
        "version": 1,
        "exported_at": now.isoformat().replace("+00:00", "Z"),
        "source_library_name": library.get("name", ""),
    }

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
                tar, "library.json",
                json.dumps(library_payload, indent=2, default=str).encode("utf-8"),
                mtime,
            )
            _tar_add_bytes(
                tar, "documents.json",
                json.dumps(documents, indent=2, default=str).encode("utf-8"),
                mtime,
            )

    archive_bytes = buf.getvalue()

    name_slug = _slug(library.get("name", ""))
    date_slug = now.strftime("%Y%m%d")
    filename = f"knowledge-{name_slug}-{date_slug}.chatsune-knowledge.tar.gz"

    _log.info(
        "knowledge_export.done user_id=%s library_id=%s bytes=%d documents=%d",
        user_id, library_id, len(archive_bytes), len(documents),
    )

    return archive_bytes, filename
