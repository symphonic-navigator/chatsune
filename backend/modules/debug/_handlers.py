"""Admin debug HTTP routes.

These endpoints are restricted to admin / master_admin via
``require_admin``. They expose the diagnostic snapshot collected by
``backend.modules.debug._collector``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from backend.dependencies import require_admin
from backend.modules.debug._collector import collect_snapshot
from shared.dtos.debug import DebugSnapshotDto

_log = logging.getLogger("chatsune.debug.handlers")

router = APIRouter(prefix="/api/admin/debug", tags=["admin-debug"])


@router.get("/snapshot", response_model=DebugSnapshotDto)
async def get_debug_snapshot(
    user: dict = Depends(require_admin),
) -> DebugSnapshotDto:
    """Return a fresh diagnostic snapshot.

    Always returns a snapshot — individual subsystem failures are
    swallowed inside the collector and surface as empty sections.
    """
    snapshot = await collect_snapshot()
    _log.debug(
        "debug snapshot served to admin=%s active_inferences=%d jobs=%d locks=%d",
        user.get("sub"),
        len(snapshot.active_inferences),
        len(snapshot.jobs),
        len(snapshot.locks),
    )
    return snapshot
