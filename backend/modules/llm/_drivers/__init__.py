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


def match_driver(*, adapter_type: str, slug: str) -> type[Driver] | None:
    """Return the first registered driver whose PATTERNS match the slug
    basename AND whose SUPPORTED_ADAPTERS contains ``adapter_type``, or
    None.

    The slug basename is everything after the last ``/`` — e.g.
    ``"deepseek/deepseek-v4-pro"`` -> ``"deepseek-v4-pro"``,
    ``"deepseek-v4-pro"`` -> ``"deepseek-v4-pro"``,
    ``"TEE/deepseek-v4-pro"`` -> ``"deepseek-v4-pro"``.

    Matching is adapter-aware: a driver that claims a slug family on
    one router but not another (e.g. MiMo on Novita only, Kimi on
    Ollama and Novita only) will not be returned for adapters it does
    not support, so listings on other routers fall cleanly through to
    the YAML lookup, the adapter heuristic, or the universal default.
    See the ``SUPPORTED_ADAPTERS`` docstring on the ``Driver`` protocol.

    First match wins, in DRIVER_REGISTRY order.
    """
    basename = slug.rsplit("/", 1)[-1]
    for driver_cls in DRIVER_REGISTRY:
        if adapter_type not in driver_cls.SUPPORTED_ADAPTERS:
            continue
        for pattern in driver_cls.PATTERNS:
            if fnmatch.fnmatch(basename, pattern):
                return driver_cls
    return None
