"""Version resolution for the running backend build.

Resolution order (first hit wins, then cached for the process lifetime):

1. ``CHATSUNE_VERSION`` env var — set by the Docker image at build time.
2. ``/app/VERSION`` file — also written by the Docker image.
3. ``version.txt`` at the repo root — used by local dev runs. The
   suffix ``-dev`` is appended so it's obvious the build isn't from CI.
4. ``0.0.0-unknown`` — last-resort fallback. Never expected in practice.

The two optional env vars ``CHATSUNE_GIT_SHA`` and ``CHATSUNE_BUILT_AT``
are pass-throughs from CI build-args. ``None`` when unset.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from shared.dtos.system import VersionDto

_log = logging.getLogger("chatsune.system.version")

# Path: backend/modules/system/_version.py → repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DOCKER_VERSION_FILE = Path("/app/VERSION")
_REPO_VERSION_FILE = _REPO_ROOT / "version.txt"

_FALLBACK_VERSION = "0.0.0-unknown"


def _read_version_file(path: Path) -> str | None:
    """Read a version file, stripping all surrounding whitespace.

    Returns ``None`` if the file does not exist, is unreadable, or empty.
    """

    try:
        if not path.is_file():
            return None
        raw = path.read_text(encoding="utf-8").strip()
        return raw or None
    except OSError as exc:
        _log.warning("Could not read version file %s: %s", path, exc)
        return None


def _compute_version() -> str:
    """Resolve the version string per the documented precedence order."""

    env_version = os.environ.get("CHATSUNE_VERSION", "").strip()
    if env_version:
        return env_version

    docker_version = _read_version_file(_DOCKER_VERSION_FILE)
    if docker_version:
        return docker_version

    repo_version = _read_version_file(_REPO_VERSION_FILE)
    if repo_version:
        # Dev run — annotate clearly so operators don't confuse a local
        # build with a CI artifact tagged from the same version.txt.
        return f"{repo_version}-dev"

    return _FALLBACK_VERSION


@lru_cache(maxsize=1)
def resolve_version() -> VersionDto:
    """Resolve and cache the running build's version descriptor.

    Cached for the process lifetime — version cannot change without a
    restart, so re-reading the filesystem on every request is wasted
    work.
    """

    version = _compute_version()
    git_sha = os.environ.get("CHATSUNE_GIT_SHA", "").strip() or None
    built_at = os.environ.get("CHATSUNE_BUILT_AT", "").strip() or None
    _log.info(
        "Resolved build version: version=%s git_sha=%s built_at=%s",
        version, git_sha, built_at,
    )
    return VersionDto(version=version, git_sha=git_sha, built_at=built_at)
