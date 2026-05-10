"""Driver registry and dispatch.

See devdocs/specs/driver-layer.md.
"""
from __future__ import annotations

import fnmatch

from backend.modules.llm._drivers._protocol import Driver
from backend.modules.llm._drivers.deepseek_v4 import DeepSeekV4Driver

DRIVER_REGISTRY: list[type[Driver]] = [
    DeepSeekV4Driver,
]


def match_driver(slug: str) -> type[Driver] | None:
    """Return the first registered driver whose PATTERNS match the slug
    basename, or None.

    See match_driver docstring in Task 2 for the basename semantics.
    """
    basename = slug.rsplit("/", 1)[-1]
    for driver_cls in DRIVER_REGISTRY:
        for pattern in driver_cls.PATTERNS:
            if fnmatch.fnmatch(basename, pattern):
                return driver_cls
    return None
