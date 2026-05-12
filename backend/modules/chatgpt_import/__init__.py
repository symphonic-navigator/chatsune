"""ChatGPT-import module — import ChatGPT export bundles as native sessions.

Public API: import only from this file. Internal modules (``_parser``,
``_repository``, ``_service``, ``_handlers``, ``_session_builder``,
``_models``) must never be imported from outside this module.
"""

from backend.modules.chatgpt_import._handlers import router
from backend.modules.chatgpt_import._memory_batch_repository import (
    ChatGptImportMemoryBatchRepository,
)
from backend.modules.chatgpt_import._repository import ChatGptImportRepository
from backend.modules.chatgpt_import._service import (
    ChatGptImportService,
    ImportConflictError,
    ImportNotFoundError,
)


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the chatgpt_import collections."""
    await ChatGptImportRepository(db).create_indexes()
    await ChatGptImportMemoryBatchRepository(db).ensure_indexes()


__all__ = [
    "router",
    "init_indexes",
    "ChatGptImportService",
    "ChatGptImportMemoryBatchRepository",
    "ImportConflictError",
    "ImportNotFoundError",
]
