import logging
from pathlib import Path
from uuid import uuid4

from backend.config import settings

logger = logging.getLogger(__name__)


class AvatarStore:
    def __init__(self) -> None:
        self._root = Path(settings.avatar_root)
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, extension: str) -> str:
        """Save avatar data and return the filename (uuid.ext)."""
        filename = f"{uuid4()}.{extension}"
        path = self._root / filename
        path.write_bytes(data)
        return filename

    def load(self, filename: str) -> bytes | None:
        """Load avatar data by filename."""
        path = self._root / filename
        if not path.exists():
            return None
        return path.read_bytes()

    def delete(self, filename: str) -> str | None:
        """Delete an avatar file.

        Returns ``None`` on success (a missing file counts as success because
        the post-condition — file does not exist — is already met). Returns
        a short human-readable error string on a real I/O failure so the
        cascade-delete report can surface it as a warning.
        """
        path = self._root / filename
        try:
            path.unlink(missing_ok=True)
            return None
        except OSError as exc:
            logger.warning("Failed to delete avatar: %s (%s)", filename, exc)
            return f"avatar file '{filename}': {exc}"
