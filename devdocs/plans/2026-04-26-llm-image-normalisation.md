# LLM Image Normalisation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single normaliser that converts every image sent to an upstream LLM provider into a JPEG with longest edge ≤ 1024 px, EXIF rotation honoured then stripped, alpha flattened on white.

**Architecture:** New private module `backend/modules/llm/_image_normaliser.py` with one function `normalise_for_llm(bytes, media_type) → (jpeg_bytes, "image/jpeg")`. Wired in at one chokepoint inside `_resolve_attachment_files()` in the chat orchestrator — that single placement covers user uploads, generated-image feedback, **and** vision-fallback (which consumes bytes from the same dict produced by that resolver). Adapters stay unchanged.

**Tech Stack:** Python 3.12+, Pillow (already a dep), pytest. No new dependencies.

**Spec:** `devdocs/specs/2026-04-26-llm-image-normalisation-design.md`

**Note on chokepoint count:** The spec describes three logical image streams (user uploads, generated images, vision fallback). On inspection of the actual code, all three flow through bytes loaded by `_resolve_attachment_files()` (`backend/modules/chat/_orchestrator.py:252`). One normalisation call inside that resolver therefore covers all three — even tighter than the spec promises. The plan exploits this.

---

## File Structure

**New files:**
- `backend/modules/llm/_image_normaliser.py` — the normaliser (single function + typed exception)
- `backend/tests/modules/llm/test_image_normaliser.py` — unit tests

**Modified files:**
- `backend/modules/llm/__init__.py` — export `normalise_for_llm` and `ImageNormalisationError` in the public API
- `backend/modules/chat/_orchestrator.py` — call the normaliser inside `_resolve_attachment_files()` for image MIME types; handle `ImageNormalisationError` by dropping the attachment and emitting an `ErrorEvent`

**No changes needed in:**
- LLM adapters (`_xai_http.py`, `_mistral_http.py`, `_nano_gpt_http.py`, `_ollama_http.py`) — they continue to receive the dict shape they already expect, but the bytes will already be normalised JPEG.
- `_vision_fallback.py` — `describe_image` keeps its current signature; the `image_bytes` it receives are already normalised because the orchestrator's `_resolve_image_attachments_for_inference` passes through `f["data"]` from the resolved file dict.
- Frontend, DTOs, MongoDB schemas, upload validation.

---

## Task 1: Create the image normaliser (TDD)

**Files:**
- Create: `backend/modules/llm/_image_normaliser.py`
- Test: `backend/tests/modules/llm/test_image_normaliser.py`

### Step 1.1: Write the failing tests

- [ ] **Step 1.1:** Create the test file with all six tests upfront. They will all fail until the implementation exists.

Create `backend/tests/modules/llm/test_image_normaliser.py`:

```python
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
```

- [ ] **Step 1.2:** Run the tests to verify they fail with `ImportError` (module does not exist yet).

Run:
```bash
cd /home/chris/workspace/chatsune
uv run pytest backend/tests/modules/llm/test_image_normaliser.py -v
```

Expected: All tests collected fail with `ModuleNotFoundError: No module named 'backend.modules.llm._image_normaliser'` (or pytest reports them as errors at collection time).

### Step 1.3: Write the implementation

- [ ] **Step 1.3:** Create `backend/modules/llm/_image_normaliser.py`:

```python
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
```

- [ ] **Step 1.4:** Run the tests, verify they all pass.

Run:
```bash
cd /home/chris/workspace/chatsune
uv run pytest backend/tests/modules/llm/test_image_normaliser.py -v
```

Expected: All seven tests pass.

If any fail, fix the implementation (not the tests) and re-run.

- [ ] **Step 1.5:** Quick syntax/lint check on the new file.

Run:
```bash
cd /home/chris/workspace/chatsune
uv run python -m py_compile backend/modules/llm/_image_normaliser.py
```

Expected: no output, exit code 0.

- [ ] **Step 1.6:** Commit.

```bash
cd /home/chris/workspace/chatsune
git add backend/modules/llm/_image_normaliser.py backend/tests/modules/llm/test_image_normaliser.py
git commit -m "$(cat <<'EOF'
Add LLM image normaliser

Single-function module that converts arbitrary image bytes into a JPEG
suitable for upstream LLM providers: longest edge ≤ 1024 px, EXIF
orientation honoured then stripped, alpha flattened on white, animated
GIFs reduced to first frame. Quality 85, progressive, optimised. Raises
ImageNormalisationError on undecodable input.

Spec: devdocs/specs/2026-04-26-llm-image-normalisation-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Wire the normaliser into the chat orchestrator

**Files:**
- Modify: `backend/modules/llm/__init__.py` — export the normaliser
- Modify: `backend/modules/chat/_orchestrator.py:252-294` — call normaliser inside `_resolve_attachment_files()` for image MIME types; handle errors in `_resolve_image_attachments_for_inference`

### Step 2.1: Export from the LLM module's public API

- [ ] **Step 2.1:** Add the export to `backend/modules/llm/__init__.py`. Insert the import near the other module-level imports (after the line `from backend.modules.llm._handlers import router` is fine — pick the alphabetically nearest place):

Add this import:

```python
from backend.modules.llm._image_normaliser import (
    ImageNormalisationError,
    normalise_for_llm,
)
```

And add both names to the `__all__` list (the list near the bottom of the file, currently ending with `"LlmService",`):

```python
__all__ = [
    # ... existing entries ...
    "LlmService",
    "ImageNormalisationError",
    "normalise_for_llm",
]
```

- [ ] **Step 2.2:** Verify the import works.

Run:
```bash
cd /home/chris/workspace/chatsune
uv run python -c "from backend.modules.llm import normalise_for_llm, ImageNormalisationError; print('ok')"
```

Expected: `ok`

### Step 2.3: Call the normaliser inside `_resolve_attachment_files`

- [ ] **Step 2.3:** Modify `backend/modules/chat/_resolve_attachment_files()` (`backend/modules/chat/_orchestrator.py:252`) to normalise image-type entries after the `files` list is fully assembled.

First, add the import near the top of `_orchestrator.py` (with the other LLM-module imports):

```python
from backend.modules.llm import ImageNormalisationError, normalise_for_llm
```

Then change the function. The current end of the function looks like this (line 287-294):

```python
        files.append({
            "_id": detail.id,
            "user_id": user_id,
            "display_name": detail.prompt or "Generated image",
            "media_type": content_type,
            "data": data,
        })
    return files
```

Replace the trailing `return files` with a normalisation pass that runs over **every** image-mime entry (covers both storage and generated-image branches in one go):

```python
        files.append({
            "_id": detail.id,
            "user_id": user_id,
            "display_name": detail.prompt or "Generated image",
            "media_type": content_type,
            "data": data,
        })

    # Normalise every image attachment to JPEG ≤ 1024 px before the bytes
    # leave the backend toward any LLM provider. Non-image attachments pass
    # through untouched. Failures are signalled by replacing the file dict's
    # data with None and tagging it with a "_normalisation_error" key — the
    # downstream call site (_resolve_image_attachments_for_inference) drops
    # those entries and emits a recoverable ErrorEvent.
    for f in files:
        media_type = f.get("media_type") or ""
        if not media_type.startswith("image/") or not f.get("data"):
            continue
        try:
            new_data, new_media_type = normalise_for_llm(f["data"], media_type)
        except ImageNormalisationError as exc:
            _log.warning(
                "attachment normalisation failed: file_id=%s media_type=%s reason=%s",
                f.get("_id"), media_type, exc.reason,
            )
            f["data"] = None
            f["_normalisation_error"] = exc.reason
            continue
        f["data"] = new_data
        f["media_type"] = new_media_type
    return files
```

(`_log` already exists at module top of the orchestrator. If the file uses a different logger name, use that name; do not add a new one.)

- [ ] **Step 2.4:** Run a syntax check on the orchestrator.

Run:
```bash
cd /home/chris/workspace/chatsune
uv run python -m py_compile backend/modules/chat/_orchestrator.py
```

Expected: no output, exit code 0.

### Step 2.5: Handle the error case in `_resolve_image_attachments_for_inference`

- [ ] **Step 2.5:** Modify `_resolve_image_attachments_for_inference` (`backend/modules/chat/_orchestrator.py:297`) to drop attachments tagged with `_normalisation_error` and emit an `ErrorEvent` so the user sees a recoverable error pill instead of a silent dropout.

Find the loop body that begins (around line 327):

```python
    for f in files:
        if f.get("data") and f["media_type"].startswith("image/"):
```

Add a branch for the failure case **just before** that condition. The new branch checks for `_normalisation_error` and emits an `ErrorEvent`:

```python
    # Local import — ErrorEvent lives in shared/events/system.
    from shared.events.system import ErrorEvent

    for f in files:
        if f.get("_normalisation_error"):
            await emit_event(ErrorEvent(
                correlation_id=correlation_id,
                error_code="image_normalisation_failed",
                recoverable=True,
                user_message=(
                    f"Couldn't process image '{f.get('display_name') or 'attachment'}' "
                    f"— it was dropped from this turn."
                ),
                detail=f.get("_normalisation_error"),
            ))
            continue

        if f.get("data") and f["media_type"].startswith("image/"):
            # ... existing body unchanged ...
```

Leave the rest of the function body unchanged. The existing `elif f.get("data"):` text-attachment branch still works because failed images have `data = None` and would simply be skipped.

- [ ] **Step 2.6:** Verify the `ErrorEvent` import exists or add it. Check the existing imports near the top of `_orchestrator.py`. If `ErrorEvent` is not already imported at module scope, leave the local import inside the function (it keeps the import surface minimal and matches the existing pattern of local imports for cross-module events in this file — see e.g. the `from backend.modules.images import get_image_service` local import at line 271).

- [ ] **Step 2.7:** Re-run the new normaliser tests to confirm nothing broke and the orchestrator file still compiles end-to-end.

Run:
```bash
cd /home/chris/workspace/chatsune
uv run pytest backend/tests/modules/llm/test_image_normaliser.py -v
uv run python -m py_compile backend/modules/chat/_orchestrator.py
```

Expected: 7 tests pass; py_compile silent.

- [ ] **Step 2.8:** Commit.

```bash
cd /home/chris/workspace/chatsune
git add backend/modules/llm/__init__.py backend/modules/chat/_orchestrator.py
git commit -m "$(cat <<'EOF'
Wire image normaliser into chat orchestrator

Every image attachment resolved by _resolve_attachment_files (covering
user uploads, generated-image feedback, and the vision-fallback bytes
that flow through the same dict) is now normalised to JPEG ≤ 1024 px
before any base64 encoding or adapter call. Decoding failures become a
recoverable ErrorEvent (image_normalisation_failed) and the offending
attachment is dropped for that turn.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Regression check on the wider test suite

This task verifies that nothing existing depends on the old "image bytes pass through unchanged" behaviour.

**Note on test scope (from project memory):** four MongoDB-using test files cannot run on the host without Docker. Do NOT instruct subagents to run "the full backend suite" without exclusions.

### Step 3.1: Identify the always-skip-on-host test files

- [ ] **Step 3.1:** Verify the list of MongoDB-dependent tests that must be excluded on the host.

Run:
```bash
cd /home/chris/workspace/chatsune
grep -lr "AsyncMongoMockClient\|motor\.motor_asyncio\.AsyncIOMotorClient(\|get_db()" backend/tests/ 2>/dev/null | grep -v __pycache__ | head -20
```

Expected: a small list of files. Cross-reference with project memory `feedback_db_tests_on_host.md` for the canonical 4-file ignore list. If unsure, run the full suite from inside the dev Docker container instead (next sub-step).

### Step 3.2: Run the safe-on-host backend test subset

- [ ] **Step 3.2:** Run all backend tests **except** the DB-dependent ones.

Run (substitute the actual ignore list from Step 3.1; example uses placeholders that should be replaced):

```bash
cd /home/chris/workspace/chatsune
uv run pytest backend/tests/ -v \
  --ignore=backend/tests/modules/<db-test-1>.py \
  --ignore=backend/tests/modules/<db-test-2>.py \
  --ignore=backend/tests/modules/<db-test-3>.py \
  --ignore=backend/tests/modules/<db-test-4>.py
```

Expected: green. If any pre-existing test breaks because it asserts something about image bytes being passed through unchanged, that is a real regression of this plan — investigate, do not paper over.

### Step 3.3: Frontend-side type/build sanity

- [ ] **Step 3.3:** No frontend changes were made in this plan, but run a build check anyway since the project guideline is to keep the build green.

Run:
```bash
cd /home/chris/workspace/chatsune/frontend
pnpm tsc --noEmit
```

Expected: no errors.

(If the project has a one-shot `pnpm build` command that is faster to run, that is acceptable instead.)

- [ ] **Step 3.4:** No commit needed for this task — it is verification only.

---

## Task 4: Manual verification on the live dev backend

These steps come from the spec's "Manual verification" section. They are not automatable and must be performed by a human (Chris) at the keyboard with the frontend open. The implementation is **not** considered complete until all five pass.

**Each step is observed twice:**
1. **Visually**, in the chat UI — does the assistant respond sensibly?
2. **In the backend log**, by grepping for `module=llm.image_normaliser` — does the expected log line appear with the expected fields?

### Step 4.1: Phone photo, large

- [ ] **Step 4.1:**
  1. Open chat with a vision-capable persona/model.
  2. Upload a real ~4 MB portrait JPEG straight from a phone (the kind that arrives as e.g. 4032×3024 with EXIF orientation).
  3. Ask: "what is this?"
  4. **Visual check:** the assistant describes the photo correctly oriented (e.g. if it's a portrait of a flower, it should not say the flower is sideways).
  5. **Log check:** one line `module=llm.image_normaliser` with `orig_dims=4032x3024` (or the source's actual dims), `new_dims=1024x768` (or similar long-edge=1024), `resized=True`.

### Step 4.2: Transparent PNG

- [ ] **Step 4.2:**
  1. Upload a small PNG with real transparency — e.g. an app icon saved with transparent background.
  2. Ask: "describe this".
  3. **Visual check:** the assistant describes the icon's contents — should not mention checkerboards, weird artefacts, or empty regions.
  4. **Log check:** the log line shows `flattened_alpha=True`.

### Step 4.3: Generated-image round trip

- [ ] **Step 4.3:**
  1. Trigger image generation — e.g. "draw me a blue flower" (assumes the `generate_image` tool is enabled for the persona and a TTI-capable connection exists).
  2. After the image arrives, in the next user message ask: "what do you see in the picture?"
  3. **Visual check:** the assistant's description matches the generated image.
  4. **Log check:** a log line `module=llm.image_normaliser` appears for the generated image being fed back, with `orig_media_type=image/png` and `new_dims` ≤ 1024 on long edge.

### Step 4.4: Already-small image

- [ ] **Step 4.4:**
  1. Upload a small (200×200 or thereabouts) PNG.
  2. Ask any question.
  3. **Log check:** `resized=False` but `new_bytes` differs from `orig_bytes` and the new media type the adapter sees is `image/jpeg` (the chat just needs to round-trip — the assertion lives in the log line, not the model output).

### Step 4.5: Log-line presence

- [ ] **Step 4.5:** After running steps 4.1–4.4, grep the backend log for the normaliser tag:

Run on the backend host:
```bash
grep "module=llm.image_normaliser" /var/log/chatsune-backend.log | tail -20
```
(or wherever the backend log is — `journalctl -u chatsune-backend` if running as a systemd service).

Expected: one line per image attachment per LLM call. If a vision-fallback path was exercised, the same image bytes flow through `_resolve_attachment_files()` once and the log line appears once — vision-fallback does not produce a second normalisation log entry.

### Step 4.6: Failure-path smoke (optional but recommended)

- [ ] **Step 4.6:** To prove the error branch works, construct a deliberately corrupt "image":
  1. Upload a `.jpg` file whose contents are arbitrary text (rename `notes.txt` to `notes.jpg`). The 10 MB upload limit and MIME magic-byte validator may reject this at upload time — if so, this path is already protected by upload validation; report and skip. If it passes upload, the chat turn should produce an `ErrorEvent` with `error_code=image_normalisation_failed` and the assistant turn should still proceed with the offending attachment dropped.

---

## Self-Review (performed before handing off)

The following review was run after completing the plan:

**1. Spec coverage:**
- Conversion rules (spec §3.1): six pipeline steps → all present in Task 1.3 implementation; tests in Task 1.1 cover each.
- Module layout (spec §3.2): private file in `backend/modules/llm/` → Task 1.3 creates it; public export added in Task 2.1.
- Three call sites (spec §3.3): the plan exploits the architectural opportunity that all three streams flow through `_resolve_attachment_files()`, collapsing to one chokepoint. Vision-fallback bytes are already-normalised because they come from the same dict. This is **stricter** than what the spec demands, not laxer.
- Logging (spec §3.4): one structured log line per call, fields exactly as specified → Task 1.3.
- Error handling (spec §3.5): typed exception raised → caught at orchestrator boundary → recoverable `ErrorEvent` emitted, attachment dropped → Task 2.5.
- Unit tests (spec §5.1): all six listed test cases present in Task 1.1 (and one extra test for ICC profile stripping).
- Manual verification (spec §5.2): all five steps present as Task 4.

**2. Placeholder scan:** No "TBD" / "TODO" / "implement later" / "add appropriate error handling" / "similar to Task N" in the plan body. The four `--ignore=` placeholders in Step 3.2 are intentional — the actual ignore list belongs to project state (memory entry `feedback_db_tests_on_host.md`) and the plan correctly redirects the executor to that source rather than duplicating it.

**3. Type consistency:** `normalise_for_llm` returns `tuple[bytes, str]` everywhere. `ImageNormalisationError` constructor signature `(*, original_media_type, original_bytes, reason)` matches between Task 1.3 and the catch site in Task 2.3. The `error_code` string `"image_normalisation_failed"` matches between spec §3.5 and Task 2.5.

---
