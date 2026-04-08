"""Admin debug module — diagnostic snapshots of background work + LLM
inference, exposed via admin-only HTTP routes and live WebSocket events.

This module is purely diagnostic. It does not perform any business
logic and never mutates state. Every value it surfaces is a best-effort
snapshot — treat it as observability, not authority.

Used by: ``frontend/src/app/components/admin-modal/DebugTab.tsx``.
"""

from backend.modules.debug._collector import collect_snapshot
from backend.modules.debug._handlers import router

__all__ = ["router", "collect_snapshot"]
