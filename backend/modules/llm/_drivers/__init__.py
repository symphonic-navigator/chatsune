"""Driver registry and dispatch.

See devdocs/specs/driver-layer.md.
"""
from __future__ import annotations

import fnmatch

from backend.modules.llm._drivers._protocol import Driver
from backend.modules.llm._drivers.deepseek_v4 import DeepSeekV4Driver
from backend.modules.llm._drivers.kimi_k2 import KimiK2Driver
from backend.modules.llm._drivers.mimo_v25 import MiMoV25Driver

# Order is cosmetic — DSv4, MiMo, and Kimi PATTERNS do not overlap, so
# the first-match-wins rule never has to break a tie here. New drivers
# append at the bottom unless they need to win over an earlier driver.
DRIVER_REGISTRY: list[type[Driver]] = [
    DeepSeekV4Driver,
    MiMoV25Driver,
    KimiK2Driver,
]


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
