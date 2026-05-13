"""HTTP routes for the system module."""

from __future__ import annotations

from fastapi import APIRouter

from backend.modules.system._version import resolve_version
from shared.dtos.system import VersionDto

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/version", response_model=VersionDto)
async def get_version() -> VersionDto:
    """Return the running backend's build descriptor.

    Public endpoint by design — knowing which build is live should not
    require authentication. The result is cached for the process
    lifetime; the version cannot change without a restart.
    """

    return resolve_version()
