"""Driver registry and dispatch.

Plan 1 ships an empty registry; concrete drivers register themselves
into ``DRIVER_REGISTRY`` (see DeepSeekV4Driver in Task 7). Matching is
basename-fnmatch on the slug.

See devdocs/specs/driver-layer.md.
"""
from __future__ import annotations

import fnmatch

from backend.modules.llm._drivers._protocol import Driver

DRIVER_REGISTRY: list[type[Driver]] = []


def match_driver(slug: str) -> type[Driver] | None:
    """Return the first registered driver whose PATTERNS match the slug
    basename, or None.

    The slug basename is everything after the last ``/`` — e.g.
    ``"deepseek/deepseek-v4-pro"`` -> ``"deepseek-v4-pro"``,
    ``"deepseek-v4-pro"`` -> ``"deepseek-v4-pro"``,
    ``"TEE/deepseek-v4-pro"`` -> ``"deepseek-v4-pro"``.

    First match wins, in DRIVER_REGISTRY order.
    """
    basename = slug.rsplit("/", 1)[-1]
    for driver_cls in DRIVER_REGISTRY:
        for pattern in driver_cls.PATTERNS:
            if fnmatch.fnmatch(basename, pattern):
                return driver_cls
    return None
