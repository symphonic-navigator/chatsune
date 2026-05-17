"""Auto-run startup migrations for Chatsune.

Migration files in this package follow two conventions:

- ``NNNN_<slug>.py`` (numbered, auto-run at startup) — each exposes an
  ``async def run(db) -> None`` entry point. ``run_all(db)`` imports
  every numbered module in lexical order and awaits its ``run``. Each
  script MUST be idempotent: ``run_all`` executes on every startup, so
  re-running against an already-migrated database must be a no-op.
- ``m_YYYY_MM_DD_<slug>.py`` (legacy, manual) — pre-dates this runner.
  These scripts have their own ``async def run()`` (no args), build
  the database connection internally, and are invoked manually via
  ``python -m backend.migrations.m_YYYY_MM_DD_*``. They are NOT picked
  up by ``run_all`` — leaving them out by design so we don't reach for
  ``connect_db()`` a second time during the lifespan startup.

Wired into ``backend/main.py`` via the FastAPI lifespan handler, AFTER
all module ``init_indexes`` calls (so migrations see the indexes they
may exercise) and BEFORE the app accepts requests.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
import re
from typing import Any

_log = logging.getLogger(__name__)

# Numbered auto-run files start with four digits and an underscore.
_AUTO_PATTERN = re.compile(r"^\d{4}_[a-z0-9_]+$")


def _discover_modules() -> list[str]:
    """Return the fully-qualified names of numbered migration modules, ordered."""
    import backend.migrations as pkg

    names: list[str] = []
    for mod_info in pkgutil.iter_modules(pkg.__path__):
        if _AUTO_PATTERN.match(mod_info.name):
            names.append(f"backend.migrations.{mod_info.name}")
    names.sort()
    return names


async def run_all(db: Any) -> None:
    """Run every numbered migration in lexical order.

    Each migration's ``run(db)`` must be idempotent — re-running on an
    already-migrated database must complete without modifying state.
    """
    module_names = _discover_modules()
    if not module_names:
        _log.info("migrations.run_all no_numbered_migrations_found")
        return
    _log.info("migrations.run_all start count=%d", len(module_names))
    for full_name in module_names:
        mod = importlib.import_module(full_name)
        _log.info("migrations.run_all running module=%s", full_name)
        await mod.run(db)
        _log.info("migrations.run_all done module=%s", full_name)
    _log.info("migrations.run_all complete count=%d", len(module_names))
