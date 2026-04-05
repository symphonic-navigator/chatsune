import logging
from pathlib import Path

from backend.config import settings

_log = logging.getLogger(__name__)


class BlobStore:
    def __init__(self) -> None:
        self._root = Path(settings.upload_root)

    def save(self, user_id: str, file_id: str, data: bytes) -> str:
        """Save binary data to disk. Returns the relative path."""
        rel = f"{user_id}/{file_id}.bin"
        target = self._root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return rel

    def load(self, user_id: str, file_id: str) -> bytes | None:
        """Load binary data from disk. Returns None if not found."""
        target = self._root / user_id / f"{file_id}.bin"
        if not target.is_file():
            return None
        return target.read_bytes()

    def delete(self, user_id: str, file_id: str) -> None:
        """Delete a file from disk. No-op if missing."""
        target = self._root / user_id / f"{file_id}.bin"
        try:
            target.unlink(missing_ok=True)
        except OSError:
            _log.warning("Failed to delete blob %s/%s", user_id, file_id)
