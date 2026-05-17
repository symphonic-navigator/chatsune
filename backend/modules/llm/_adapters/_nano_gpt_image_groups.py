"""Nano-gpt image group constants, payload builders, Seedream resolution table.

Two image groups live behind the nano-gpt adapter:

* ``nano_gpt_zimage`` — Z-Image-Turbo and Z-Image-Base; user picks one of nine
  fixed sizes plus a model toggle.
* ``nano_gpt_seedream`` — Seedream 4.5; aspect ratio + quality stepping that
  maps to width/height satisfying nano-gpt's 3 686 400-pixel minimum.

The resolution table is hardcoded (not computed at request time) so the same
input always hits the same upstream size — important for deterministic tests
and so support tickets can quote the exact dimensions a config produced.
"""

from __future__ import annotations

from shared.dtos.images import SeedreamConfig, ZImageConfig

ZIMAGE_GROUP_ID = "nano_gpt_zimage"
SEEDREAM_GROUP_ID = "nano_gpt_seedream"


# Aspect × Quality → (width, height). Satisfies nano-gpt's
# 3 686 400-pixel minimum and is a multiple of 32 in both dimensions.
# Quality tiers target ~3.7M / ~5M / ~7M total pixels.
SEEDREAM_RESOLUTIONS: dict[tuple[str, str], tuple[int, int]] = {
    ("1:1",  "standard"): (1920, 1920),
    ("1:1",  "high"):     (2240, 2240),
    ("1:1",  "ultra"):    (2656, 2656),
    ("16:9", "standard"): (2560, 1440),
    ("16:9", "high"):     (2976, 1664),
    ("16:9", "ultra"):    (3520, 1984),
    ("9:16", "standard"): (1440, 2560),
    ("9:16", "high"):     (1664, 2976),
    ("9:16", "ultra"):    (1984, 3520),
    ("4:3",  "standard"): (2240, 1664),
    ("4:3",  "high"):     (2592, 1952),
    ("4:3",  "ultra"):    (3072, 2304),
    ("3:4",  "standard"): (1664, 2240),
    ("3:4",  "high"):     (1952, 2592),
    ("3:4",  "ultra"):    (2304, 3072),
    ("3:2",  "standard"): (2368, 1568),
    ("3:2",  "high"):     (2752, 1824),
    ("3:2",  "ultra"):    (3264, 2176),
    ("2:3",  "standard"): (1568, 2368),
    ("2:3",  "high"):     (1824, 2752),
    ("2:3",  "ultra"):    (2176, 3264),
}


def seedream_resolution(aspect: str, quality: str) -> tuple[int, int]:
    """Look up (width, height) for an aspect × quality combination.

    Raises ``KeyError`` for unknown aspect/quality strings — the typed
    ``SeedreamConfig`` discriminated-union prevents this at the API edge,
    so a KeyError here is a programming error, not user input.
    """
    return SEEDREAM_RESOLUTIONS[(aspect, quality)]


def zimage_payload(config: ZImageConfig, prompt: str) -> dict:
    """Build the OpenAI-shaped /images/generations body for a Z-Image call."""
    return {
        "model": f"z-image-{config.model}",
        "prompt": prompt,
        "n": config.n,
        "size": config.size,
        "response_format": "url",
    }


def seedream_payload(config: SeedreamConfig, prompt: str) -> dict:
    """Build the OpenAI-shaped /images/generations body for a Seedream call."""
    w, h = seedream_resolution(config.aspect, config.quality)
    return {
        "model": "seedream-v4.5",
        "prompt": prompt,
        "n": config.n,
        "size": f"{w}x{h}",
        "response_format": "url",
    }
