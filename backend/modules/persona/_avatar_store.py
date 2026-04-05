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

    def delete(self, filename: str) -> None:
        """Delete an avatar file."""
        path = self._root / filename
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to delete avatar: %s", filename)
