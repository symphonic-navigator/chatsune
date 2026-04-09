"""Vision fallback runner.

When a persona's primary chat model does not support vision, this module
delegates image description to a separate vision-capable model. The call is
non-streaming from the caller's perspective: we consume the adapter stream
internally and return the assembled text.

Retry policy: attempt the call exactly twice. The first failure is treated as
a potential Ollama Cloud cold-start and silently retried. The second failure
raises VisionFallbackError.
"""

import base64
import logging
from contextlib import nullcontext

from backend.modules.llm import (
    ADAPTER_REGISTRY,
    PROVIDER_BASE_URLS,
    ContentDelta,
    StreamDone,
    StreamError,
    get_api_key,
    get_inference_lock,
    track_inference,
)
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart

logger = logging.getLogger(__name__)

_VISION_FALLBACK_SYSTEM_PROMPT = (
    "You are an image-description assistant. The user has attached an image for a "
    "downstream assistant that cannot see it. Describe the image in detail: subjects, "
    "objects, layout, any visible text, colours, and the overall mood. Be specific and "
    "concrete. Do not add interpretation or advice — only what is in the image."
)


class VisionFallbackError(Exception):
    """Raised when the vision fallback model fails on both attempts."""


def _get_adapter_for(model_unique_id: str):
    """Return a fresh adapter instance for the given model unique ID.

    Exists as a named function so tests can monkeypatch it.
    """
    provider_id, _ = model_unique_id.split(":", 1)
    return ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])


async def _get_api_key_for(user_id: str, model_unique_id: str) -> str:
    """Return the API key for the provider of the given model unique ID.

    Exists as a named function so tests can monkeypatch it.
    """
    provider_id, _ = model_unique_id.split(":", 1)
    return await get_api_key(user_id, provider_id)


async def describe_image(
    user_id: str,
    model_unique_id: str,
    image_bytes: bytes,
    media_type: str,
) -> str:
    """Describe an image using a vision-capable fallback model.

    Args:
        user_id: The ID of the user whose API key should be used.
        model_unique_id: Full model ID in ``<provider_id>:<model_slug>`` format.
        image_bytes: Raw image bytes to encode and send.
        media_type: MIME type of the image, e.g. ``"image/png"``.

    Returns:
        Stripped text description of the image.

    Raises:
        VisionFallbackError: If the model_unique_id format is invalid, or if
            both call attempts fail.
    """
    if ":" not in model_unique_id:
        raise VisionFallbackError(
            f"Invalid model_unique_id format (expected '<provider>:<slug>'): {model_unique_id!r}"
        )

    _, model_slug = model_unique_id.split(":", 1)
    image_data = base64.b64encode(image_bytes).decode("ascii")

    request = CompletionRequest(
        model=model_slug,
        messages=[
            CompletionMessage(
                role="system",
                content=[ContentPart(type="text", text=_VISION_FALLBACK_SYSTEM_PROMPT)],
            ),
            CompletionMessage(
                role="user",
                content=[ContentPart(type="image", data=image_data, media_type=media_type)],
            ),
        ],
        temperature=0.2,
        reasoning_enabled=False,
        supports_reasoning=False,
    )

    last_error: Exception | None = None

    provider_id, _ = model_unique_id.split(":", 1)

    for attempt in range(1, 3):
        try:
            api_key = await _get_api_key_for(user_id, model_unique_id)
            adapter = _get_adapter_for(model_unique_id)
            chunks: list[str] = []

            # Vision fallback bypasses the public stream_completion wrapper,
            # so honour the adapter's concurrency policy manually. Without
            # this, a vision fallback against ollama_local runs concurrently
            # with any in-flight chat/job inference and the engine drops one
            # of them.
            #
            # The lock is nested INSIDE track_inference so that time spent
            # waiting on the lock is not counted as inference time. We use
            # ``async with`` (and ``nullcontext`` for the no-lock case) so
            # that any exception or cancellation between acquire and the
            # stream body cannot leave the lock stuck: Lock.__aexit__ only
            # releases when __aenter__ actually acquired it.
            lock = get_inference_lock(provider_id, user_id)
            lock_ctx = lock if lock is not None else nullcontext()
            async with track_inference(
                user_id=user_id,
                provider_id=provider_id,
                model_slug=model_slug,
                source="vision_fallback",
            ):
                async with lock_ctx:
                    async for event in adapter.stream_completion(api_key, request):
                        if isinstance(event, ContentDelta):
                            chunks.append(event.delta)
                        elif isinstance(event, StreamDone):
                            break
                        elif isinstance(event, StreamError):
                            raise VisionFallbackError(f"adapter stream error: {event.message}")

            text = "".join(chunks).strip()
            if not text:
                raise VisionFallbackError("vision model returned empty description")

            return text

        except Exception as exc:
            last_error = exc
            if attempt == 1:
                logger.warning(
                    "Vision fallback attempt 1 failed, retrying",
                    extra={"model": model_unique_id, "error": str(exc)},
                )
            # Second failure falls through to raise below

    raise VisionFallbackError(
        f"Vision fallback failed after 2 attempts: {last_error}"
    ) from last_error
