"""Image normaliser for LLM transmission.

Single function applied at the chat orchestrator chokepoint before any
image bytes leave the backend toward an upstream LLM provider. Rules:

  - Output is always JPEG with media_type ``image/jpeg``.
  - Longest edge ≤ 1024 px, aspect ratio preserved (no upscaling).
  - EXIF orientation is honoured (rotate to display orientation) and then
    stripped along with all other metadata.
  - Multi-frame inputs (animated GIF) are reduced to the first frame.
  - Alpha is flattened on white (RGBA → RGB). JPEG cannot carry alpha.
  - Re-encode runs even when no resize is needed — the pipeline is
    single-path and predictable.

JPEG quality 85, ``optimize=True``, ``progressive=True``.
"""

import io
import logging
import time

from PIL import Image, ImageOps, UnidentifiedImageError

_log = logging.getLogger(__name__)

_MAX_EDGE = 1024
_JPEG_QUALITY = 85


class ImageNormalisationError(Exception):
    """Raised when Pillow cannot decode the input bytes."""

    def __init__(self, *, original_media_type: str, original_bytes: int, reason: str) -> None:
        super().__init__(
            f"image normalisation failed: media_type={original_media_type!r} "
            f"bytes={original_bytes} reason={reason}"
        )
        self.original_media_type = original_media_type
        self.original_bytes = original_bytes
        self.reason = reason


def normalise_for_llm(data: bytes, media_type: str) -> tuple[bytes, str]:
    """Normalise image bytes for transmission to an upstream LLM.

    Returns ``(jpeg_bytes, "image/jpeg")``. Raises
    :class:`ImageNormalisationError` if Pillow cannot decode the input.
    """
    started_perf = time.monotonic()
    orig_bytes = len(data)

    try:
        src = Image.open(io.BytesIO(data))
        src.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageNormalisationError(
            original_media_type=media_type,
            original_bytes=orig_bytes,
            reason=type(exc).__name__,
        ) from exc

    orig_w, orig_h = src.size

    # 1. Multi-frame inputs (animated GIF) → first frame only.
    dropped_frames = 0
    n_frames = getattr(src, "n_frames", 1)
    if n_frames > 1:
        dropped_frames = n_frames - 1
        src.seek(0)
        # Materialise the first frame so the seek is durable across mode conversion.
        src = src.copy()

    # 2. Apply EXIF orientation BEFORE stripping metadata.
    src = ImageOps.exif_transpose(src)

    # 3. Flatten alpha onto a white background. JPEG cannot carry alpha.
    flattened_alpha = False
    if src.mode in ("RGBA", "LA") or (src.mode == "P" and "transparency" in src.info):
        bg = Image.new("RGB", src.size, (255, 255, 255))
        rgba = src.convert("RGBA")
        bg.paste(rgba, mask=rgba.split()[-1])
        src = bg
        flattened_alpha = True
    elif src.mode != "RGB":
        src = src.convert("RGB")

    # 4. Resize on longest edge if larger than the cap. Never upscale.
    w, h = src.size
    longest = max(w, h)
    resized = False
    if longest > _MAX_EDGE:
        scale = _MAX_EDGE / longest
        new_size = (int(round(w * scale)), int(round(h * scale)))
        src = src.resize(new_size, Image.LANCZOS)
        resized = True

    # 5. JPEG encode. exif=b"" strips EXIF; omitting icc_profile drops it.
    out = io.BytesIO()
    src.save(
        out,
        format="JPEG",
        quality=_JPEG_QUALITY,
        optimize=True,
        progressive=True,
        exif=b"",
    )
    new_bytes_value = out.getvalue()

    duration_ms = (time.monotonic() - started_perf) * 1000
    _log.info(
        "module=llm.image_normaliser "
        "orig_bytes=%d orig_dims=%dx%d orig_media_type=%s "
        "new_bytes=%d new_dims=%dx%d "
        "duration_ms=%.1f resized=%s flattened_alpha=%s dropped_frames=%d",
        orig_bytes, orig_w, orig_h, media_type,
        len(new_bytes_value), src.size[0], src.size[1],
        duration_ms, resized, flattened_alpha, dropped_frames,
    )

    return new_bytes_value, "image/jpeg"
