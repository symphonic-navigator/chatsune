"""JPEG thumbnail generation for stored images."""

import io

from PIL import Image


def generate_thumbnail_jpeg(image_bytes: bytes, *, max_edge: int = 256) -> bytes:
    """Resize image so its longer edge is ``max_edge`` (no upscaling).

    Re-encodes as JPEG quality 80 and strips EXIF/ICC metadata.
    Aspect ratio is preserved.
    """
    src = Image.open(io.BytesIO(image_bytes))
    src.load()  # force-decode while the BytesIO is still open

    # Convert to RGB (JPEG cannot store RGBA / palette directly)
    if src.mode != "RGB":
        src = src.convert("RGB")

    w, h = src.size
    longest = max(w, h)
    if longest > max_edge:
        scale = max_edge / longest
        new_size = (int(round(w * scale)), int(round(h * scale)))
        src = src.resize(new_size, Image.LANCZOS)

    out = io.BytesIO()
    # `exif=b""` strips EXIF; we don't pass icc_profile so ICC is dropped too.
    src.save(out, format="JPEG", quality=80, optimize=True, exif=b"")
    return out.getvalue()
