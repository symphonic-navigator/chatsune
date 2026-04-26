"""Unit tests for the LLM image normaliser.

Pure function — no DB, no async, no fixtures beyond Pillow-generated
in-memory images. Runs on the host without Docker.
"""

import io

import pytest
from PIL import Image

from backend.modules.llm._image_normaliser import (
    ImageNormalisationError,
    normalise_for_llm,
)


def _make_jpeg(width: int, height: int, colour: tuple[int, int, int] = (200, 100, 50)) -> bytes:
    """Return raw JPEG bytes for a flat-colour test image."""
    img = Image.new("RGB", (width, height), colour)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _make_png_with_alpha(width: int, height: int) -> bytes:
    """Return raw PNG bytes with a fully-transparent rectangle in the centre."""
    img = Image.new("RGBA", (width, height), (255, 0, 0, 255))
    # carve a transparent rectangle in the middle
    for y in range(height // 4, 3 * height // 4):
        for x in range(width // 4, 3 * width // 4):
            img.putpixel((x, y), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_animated_gif(frames: int = 2) -> bytes:
    """Return raw bytes for a multi-frame animated GIF."""
    images = [
        Image.new("P", (40, 40), i * 50)
        for i in range(frames)
    ]
    buf = io.BytesIO()
    images[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=images[1:],
        duration=100,
        loop=0,
    )
    return buf.getvalue()


def _make_jpeg_with_exif_orientation_6() -> bytes:
    """Return a landscape-on-disk JPEG with EXIF orientation=6 (rotate 90° CW for display)."""
    # Landscape on disk: 200 wide x 100 tall, but EXIF says display rotated.
    img = Image.new("RGB", (200, 100), (10, 200, 10))
    # Build a minimal EXIF block declaring orientation=6.
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation tag
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _open(b: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(b))
    img.load()
    return img


def test_large_jpeg_resizes_to_1024_long_edge():
    src = _make_jpeg(3000, 2000)
    out_bytes, media_type = normalise_for_llm(src, "image/jpeg")
    assert media_type == "image/jpeg"
    out = _open(out_bytes)
    assert max(out.size) == 1024
    # aspect ratio preserved within rounding (3:2 → 1024:683)
    assert out.size in {(1024, 682), (1024, 683)}
    assert out.format == "JPEG"


def test_small_jpeg_kept_at_original_dimensions_but_re_encoded():
    src = _make_jpeg(600, 400)
    out_bytes, media_type = normalise_for_llm(src, "image/jpeg")
    assert media_type == "image/jpeg"
    out = _open(out_bytes)
    assert out.size == (600, 400)
    # bytes differ → re-encoding actually ran
    assert out_bytes != src


def test_png_with_alpha_is_flattened_on_white():
    src = _make_png_with_alpha(80, 60)
    out_bytes, media_type = normalise_for_llm(src, "image/png")
    assert media_type == "image/jpeg"
    out = _open(out_bytes)
    assert out.mode == "RGB"
    # The centre pixel was transparent → after flatten on white it must read as ~white.
    cx, cy = 40, 30
    r, g, b = out.getpixel((cx, cy))
    assert r > 240 and g > 240 and b > 240


def test_animated_gif_reduces_to_single_frame():
    src = _make_animated_gif(frames=3)
    out_bytes, media_type = normalise_for_llm(src, "image/gif")
    assert media_type == "image/jpeg"
    out = _open(out_bytes)
    # JPEG is single-frame by definition; verify decode works and produced one frame.
    assert getattr(out, "n_frames", 1) == 1


def test_exif_orientation_is_applied_then_stripped():
    src = _make_jpeg_with_exif_orientation_6()
    out_bytes, media_type = normalise_for_llm(src, "image/jpeg")
    assert media_type == "image/jpeg"
    out = _open(out_bytes)
    # On-disk was 200x100 (landscape). Orientation=6 means display rotated 90° CW
    # → after applying, pixel dimensions become 100x200 (portrait).
    assert out.size == (100, 200)
    # No EXIF in output
    assert "exif" not in out.info


def test_output_strips_icc_profile():
    # Build a JPEG with an ICC profile so we can prove it is dropped.
    img = Image.new("RGB", (50, 50), (100, 150, 200))
    buf = io.BytesIO()
    fake_icc = b"icc-profile-bytes-for-test-only"
    img.save(buf, format="JPEG", icc_profile=fake_icc)
    out_bytes, _ = normalise_for_llm(buf.getvalue(), "image/jpeg")
    out = _open(out_bytes)
    assert "icc_profile" not in out.info


def test_corrupt_bytes_raise_typed_error():
    with pytest.raises(ImageNormalisationError):
        normalise_for_llm(b"not an image at all", "image/jpeg")
