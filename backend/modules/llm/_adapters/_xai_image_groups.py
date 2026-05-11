"""xAI grok-imagine image group definition.

Verified against the live xAI API on 2026-04-26 with the project's
.xai-test-key. See devdocs/specs/2026-04-26-tti-xai-imagine-design.md
section 12 for the canonical findings.
"""

GROUP_ID = "xai_imagine"


def model_id_for_tier(tier: str) -> str:
    """Map config tier to xAI's model id.

    Verified against the live xAI API; ``grok-imagine-image-pro`` was
    deprecated on 2026-05-15 in favour of ``grok-imagine-image-quality``.
    Docs: https://docs.x.ai/developers/model-capabilities/images/generation
    """
    if tier == "quality":
        return "grok-imagine-image-quality"
    return "grok-imagine-image"


def aspect_to_payload(aspect: str) -> str:
    """xAI takes the aspect literal directly (e.g. '16:9')."""
    return aspect


def resolution_to_payload(resolution: str) -> str:
    """xAI takes '1k' or '2k' directly."""
    return resolution
