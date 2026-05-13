"""System-level DTOs.

Platform-wide concerns that don't fit any single domain module — currently
just the build/version descriptor returned by ``GET /api/version``.

The version endpoint is public (no auth) and feeds operator-facing tooling
(deploy verification, CI smoke tests, future UI display). Keep this DTO
stable; treat it as part of the wire contract.
"""

from __future__ import annotations

from pydantic import BaseModel


class VersionDto(BaseModel):
    """Identifies the running backend build.

    - ``version``: semver-shaped string, e.g. ``0.1.0`` (release),
      ``0.1.0-pre.25`` (pre-release CI build), ``0.1.0-dev`` (local dev
      run), or ``0.0.0-unknown`` if no source could be resolved.
    - ``git_sha``: full or short git SHA of the source tree the build was
      cut from. ``None`` when running outside a CI build.
    - ``built_at``: ISO-8601 UTC timestamp of when the image was built.
      ``None`` when running outside a CI build.
    """

    version: str
    git_sha: str | None = None
    built_at: str | None = None
