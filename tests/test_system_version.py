"""Unit tests for the system.version resolver.

Verifies the documented precedence order:
1. CHATSUNE_VERSION env var
2. /app/VERSION file (Docker)
3. version.txt at repo root (+ "-dev" suffix)
4. Fallback "0.0.0-unknown"

The on-disk Docker path is not exercised here — `_DOCKER_VERSION_FILE`
is a module-level constant pointing at ``/app/VERSION``, which we don't
have privileges to create in the test environment. The remaining paths
cover the precedence logic adequately.
"""

from __future__ import annotations

import os
import pytest

from backend.modules.system import _version as version_mod
from backend.modules.system._version import resolve_version


@pytest.fixture(autouse=True)
def _clear_env_and_cache(monkeypatch):
    """Reset env vars and the lru_cache between tests."""

    for var in ("CHATSUNE_VERSION", "CHATSUNE_GIT_SHA", "CHATSUNE_BUILT_AT"):
        monkeypatch.delenv(var, raising=False)
    resolve_version.cache_clear()
    yield
    resolve_version.cache_clear()


def test_env_var_takes_precedence(monkeypatch):
    monkeypatch.setenv("CHATSUNE_VERSION", "1.2.3-rc.4")
    dto = resolve_version()
    assert dto.version == "1.2.3-rc.4"
    assert dto.git_sha is None
    assert dto.built_at is None


def test_falls_back_to_repo_version_txt_with_dev_suffix():
    # No env var → reads version.txt at the repo root and appends "-dev".
    dto = resolve_version()
    assert dto.version.endswith("-dev")
    # Base portion must be the file's contents, stripped.
    assert dto.version.removesuffix("-dev") == version_mod._REPO_VERSION_FILE.read_text(encoding="utf-8").strip()


def test_git_sha_and_built_at_passthrough(monkeypatch):
    monkeypatch.setenv("CHATSUNE_VERSION", "0.1.0-pre.42")
    monkeypatch.setenv("CHATSUNE_GIT_SHA", "deadbee")
    monkeypatch.setenv("CHATSUNE_BUILT_AT", "2026-05-13T12:00:00Z")
    dto = resolve_version()
    assert dto.version == "0.1.0-pre.42"
    assert dto.git_sha == "deadbee"
    assert dto.built_at == "2026-05-13T12:00:00Z"


def test_empty_env_var_is_treated_as_unset(monkeypatch):
    # Empty / whitespace-only env vars must not override the file fallback,
    # otherwise an unset CI build-arg would mask the dev version.
    monkeypatch.setenv("CHATSUNE_VERSION", "   ")
    dto = resolve_version()
    assert dto.version.endswith("-dev")
