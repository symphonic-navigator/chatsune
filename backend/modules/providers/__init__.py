"""Premium Provider Accounts module — public API.

Exposes:
  - ``PremiumProviderService``: thin facade over the repository and registry.
  - ``PremiumProviderAccountRepository``: re-exported for dependency wiring
    (tests, admin cleanup paths, etc.).
  - ``PremiumProviderNotFoundError`` / ``PremiumProviderAccountNotFoundError``:
    domain exceptions surfaced to the HTTP layer.
  - ``router``: the ``/api/providers`` FastAPI router, mounted from
    ``backend/main.py`` in a later task.

All other members of the module are private (``_registry``, ``_repository``,
``_handlers``, ``_models``) and must not be imported from outside this module.
"""
from __future__ import annotations

from backend.modules.providers._handlers import router
from backend.modules.providers._registry import (
    get as get_definition,
    get_all as get_all_definitions,
)
from backend.modules.providers._repository import (
    PremiumProviderAccountRepository,
)
from shared.dtos.providers import PremiumProviderDefinitionDto


class PremiumProviderNotFoundError(Exception):
    """Unknown provider id — not registered."""


class PremiumProviderAccountNotFoundError(Exception):
    """No account configured for the given (user, provider)."""


class PremiumProviderService:
    """Thin facade combining the static registry with per-user account storage.

    All methods return plain dicts (produced via ``model_dump()``) so that the
    HTTP layer can hand them straight back to FastAPI without a second
    serialisation step.
    """

    def __init__(self, repo: PremiumProviderAccountRepository) -> None:
        self._repo = repo

    async def catalogue(self) -> list[dict]:
        return [
            PremiumProviderDefinitionDto(
                id=d.id,
                display_name=d.display_name,
                icon=d.icon,
                base_url=d.base_url,
                capabilities=list(d.capabilities),
                config_fields=list(d.config_fields),
                linked_integrations=list(d.linked_integrations),
            ).model_dump()
            for d in get_all_definitions().values()
        ]

    async def list_for_user(self, user_id: str) -> list[dict]:
        # Pipe every document through to_dto so we never leak config_encrypted
        # across the module boundary (Task 4 review — I-2).
        docs = await self._repo.list_for_user(user_id)
        return [self._repo.to_dto(d).model_dump() for d in docs]

    async def get(self, user_id: str, provider_id: str) -> dict | None:
        if get_definition(provider_id) is None:
            raise PremiumProviderNotFoundError(provider_id)
        doc = await self._repo.find(user_id, provider_id)
        if doc is None:
            return None
        return self._repo.to_dto(doc).model_dump()

    async def upsert(
        self, user_id: str, provider_id: str, config: dict,
    ) -> dict:
        if get_definition(provider_id) is None:
            raise PremiumProviderNotFoundError(provider_id)
        doc = await self._repo.upsert(user_id, provider_id, config)
        return self._repo.to_dto(doc).model_dump()

    async def delete(self, user_id: str, provider_id: str) -> bool:
        return await self._repo.delete(user_id, provider_id)

    async def get_decrypted_secret(
        self, user_id: str, provider_id: str, field: str,
    ) -> str | None:
        doc = await self._repo.find(user_id, provider_id)
        if doc is None:
            return None
        return self._repo.get_decrypted_secret(doc, field)

    async def has_account(self, user_id: str, provider_id: str) -> bool:
        return await self._repo.find(user_id, provider_id) is not None

    async def delete_all_for_user(self, user_id: str) -> int:
        return await self._repo.delete_all_for_user(user_id)


__all__ = [
    "PremiumProviderService",
    "PremiumProviderAccountRepository",
    "PremiumProviderNotFoundError",
    "PremiumProviderAccountNotFoundError",
    "router",
]
