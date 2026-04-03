"""Settings module -- platform-wide admin-managed configuration.

Public API: import only from this file.
"""

from backend.modules.settings._handlers import router
from backend.modules.settings._repository import SettingsRepository


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the settings module collections."""
    await SettingsRepository(db).create_indexes()


__all__ = ["router", "init_indexes", "SettingsRepository"]
