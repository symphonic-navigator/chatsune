import logging
import uuid
from pathlib import Path

from backend.config import settings

_log = logging.getLogger(__name__)


def _validate_uuid(value: str, field: str) -> None:
    """Defensive check that a path component is a real UUID.

    Both ``user_id`` (from JWT sub) and ``file_id`` (from uuid4) are expected
    to be UUID strings. A round-trip through :class:`uuid.UUID` rejects any
    value containing slashes, ``..``, whitespace or other path-traversal
    characters before it ever touches the filesystem.
    """
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{field} must be a valid UUID string") from exc


class BlobStore:
    def __init__(self) -> None:
        self._root = Path(settings.upload_root)

    def save(self, user_id: str, file_id: str, data: bytes) -> str:
        """Save binary data to disk. Returns the relative path."""
        _validate_uuid(user_id, "user_id")
        _validate_uuid(file_id, "file_id")
        rel = f"{user_id}/{file_id}.bin"
        target = self._root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return rel

    def load(self, user_id: str, file_id: str) -> bytes | None:
        """Load binary data from disk. Returns None if not found."""
        _validate_uuid(user_id, "user_id")
        _validate_uuid(file_id, "file_id")
        target = self._root / user_id / f"{file_id}.bin"
        if not target.is_file():
            return None
        return target.read_bytes()

    def delete(self, user_id: str, file_id: str) -> str | None:
        """Delete a file from disk. No-op if missing.

        Returns ``None`` on success (a missing file counts as success because
        the post-condition — file does not exist — is already met). Returns
        a short human-readable error string on a real I/O failure so the
        cascade-delete report can surface it as a warning.
        """
        _validate_uuid(user_id, "user_id")
        _validate_uuid(file_id, "file_id")
        target = self._root / user_id / f"{file_id}.bin"
        try:
            target.unlink(missing_ok=True)
            return None
        except OSError as exc:
            _log.warning("Failed to delete blob %s/%s (%s)", user_id, file_id, exc)
            return f"blob '{file_id}': {exc}"
