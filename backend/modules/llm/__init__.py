"""LLM module — inference provider adapters, user credentials, model metadata.

Public API: import only from this file.
"""

from backend.modules.llm._credentials import CredentialRepository
from backend.modules.llm._curation import CurationRepository
from backend.modules.llm._handlers import router
from backend.modules.llm._registry import ADAPTER_REGISTRY
from backend.modules.llm._user_config import UserModelConfigRepository
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the LLM module collections."""
    await CredentialRepository(db).create_indexes()
    await CurationRepository(db).create_indexes()
    await UserModelConfigRepository(db).create_indexes()


def is_valid_provider(provider_id: str) -> bool:
    """Return True if provider_id is registered in the adapter registry."""
    return provider_id in ADAPTER_REGISTRY


__all__ = ["router", "init_indexes", "is_valid_provider", "UserModelConfigRepository"]
