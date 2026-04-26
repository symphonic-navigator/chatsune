import io

from PIL import Image

from backend.modules.images._thumbnails import generate_thumbnail_jpeg


def _make_png(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), color=(128, 64, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_generate_thumbnail_landscape():
    src = _make_png(1024, 512)
    thumb_bytes = generate_thumbnail_jpeg(src, max_edge=256)
    thumb = Image.open(io.BytesIO(thumb_bytes))
    assert thumb.format == "JPEG"
    assert max(thumb.size) == 256
    assert thumb.size == (256, 128)


def test_generate_thumbnail_portrait():
    src = _make_png(512, 1024)
    thumb_bytes = generate_thumbnail_jpeg(src, max_edge=256)
    thumb = Image.open(io.BytesIO(thumb_bytes))
    assert thumb.size == (128, 256)


def test_generate_thumbnail_smaller_than_max_is_passthrough_dimensions():
    src = _make_png(100, 50)
    thumb_bytes = generate_thumbnail_jpeg(src, max_edge=256)
    thumb = Image.open(io.BytesIO(thumb_bytes))
    # We don't upscale.
    assert thumb.size == (100, 50)


def test_generate_thumbnail_strips_metadata():
    """JPEG output must not carry EXIF/ICC metadata."""
    src = _make_png(512, 512)
    thumb_bytes = generate_thumbnail_jpeg(src, max_edge=256)
    thumb = Image.open(io.BytesIO(thumb_bytes))
    # Pillow exposes exif via ._getexif() for JPEG; ours should be empty/None
    exif = thumb.getexif()
    assert len(exif) == 0
