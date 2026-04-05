import base64
import io
import logging

from PIL import Image

_log = logging.getLogger(__name__)

_MAX_WIDTH = 150


def generate_thumbnail(data: bytes, max_width: int = _MAX_WIDTH) -> str | None:
    """Generate a base64-encoded JPEG thumbnail from image bytes.

    Returns None if the image cannot be processed.
    """
    try:
        img = Image.open(io.BytesIO(data))
        img = img.convert("RGB")

        if img.width > max_width:
            ratio = max_width / img.width
            new_size = (max_width, int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        _log.warning("Failed to generate thumbnail", exc_info=True)
        return None
