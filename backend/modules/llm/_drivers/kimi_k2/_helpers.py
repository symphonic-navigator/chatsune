"""Internal helpers for the Kimi K2 driver.

Kept in a separate module so ``_capability.py`` can import them
without going through the package ``__init__.py``, which would
create a circular dependency.
"""
from __future__ import annotations


_SUPPORTED_ADAPTERS: frozenset[str] = frozenset({"ollama_http", "novita_http"})


def _unsupported_adapter(adapter_type: str) -> NotImplementedError:
    """Build the canonical 'adapter not supported' error.

    Re-used across the three driver methods so the message stays in sync.
    """
    return NotImplementedError(
        f"KimiK2Driver: adapter_type={adapter_type!r} has no driver-level "
        f"support. Kimi K2.5/K2.6 is wired for ollama_http and novita_http "
        f"only; other adapter_types are intentionally unsupported to avoid "
        f"silent capability/wire-shape drift."
    )


def _kimi_version(slug: str) -> str:
    """Return ``'k2.5'`` or ``'k2.6'`` for a Kimi slug, regardless of prefix.

    PATTERNS has already matched ``kimi-k2.5*`` or ``kimi-k2.6*`` against
    the slug basename before this is called, so the slug is guaranteed to
    contain one of those substrings. The publisher prefix
    (``moonshotai/...``) is stripped first for safety.
    """
    basename = slug.rsplit("/", 1)[-1]
    if basename.startswith("kimi-k2.6"):
        return "k2.6"
    if basename.startswith("kimi-k2.5"):
        return "k2.5"
    raise ValueError(
        f"_kimi_version: slug {slug!r} did not start with a known Kimi K2 "
        f"prefix; PATTERNS should have prevented this."
    )
