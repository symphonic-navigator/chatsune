"""System module — platform-level concerns that don't belong to any domain.

Currently exposes a single read-only endpoint, ``GET /api/version``, used
for deploy verification and CI smoke tests. Public on purpose: knowing
which build is running shouldn't require authentication.

If you find yourself adding business logic here, stop and think — this
module is intentionally tiny. Most things belong elsewhere.
"""

from backend.modules.system._handlers import router
from backend.modules.system._version import resolve_version

__all__ = ["router", "resolve_version"]
