# LLM Image Normalisation — Design

**Date:** 2026-04-26
**Status:** Draft, awaiting Chris's review
**Scope:** Backend only. Single function applied at three call sites. No frontend changes, no DB changes, no DTO shape changes. One additive new `error_code` value on the existing `ErrorEvent`.

---

## 1. Problem

Images currently flow to upstream LLM providers at original resolution and in
their original encoding. Phone photos arrive as 4000×3000 JPEGs, screenshots
as several-megabyte PNGs, generated images as 1024² PNGs. Every upstream
provider — xAI, Mistral, Nano-GPT, Ollama — has size, dimension and format
constraints, and even when an upload technically fits, oversized images burn
input tokens, increase latency and occasionally trigger silent rejections.

There is no normalisation step today. The aim of this spec is to add one
small, predictable step in front of the LLM transport layer that produces
image bytes every supported upstream is happy with.

---

## 2. Goals & non-goals

### Goals

- Every image byte sequence sent to an LLM passes through one normaliser.
- Output is always JPEG, longest edge ≤ 1024 px, aspect ratio preserved,
  no metadata.
- One implementation, three call sites: user uploads in chat, generated
  images fed back to the LLM, and the vision-fallback helper path.
- Adapters (xAI / Mistral / Nano-GPT / Ollama) stay unchanged — they
  continue to receive `(base64 bytes, media_type)` and remain ignorant of
  the normalisation rules.

### Non-goals

- No change to how images are stored on disk. Originals stay as-is.
- No persistent cache of normalised bytes. Re-encode on every send is
  acceptable; the VPS has spare CPU.
- No per-adapter or per-model overrides. One rule for all upstreams.
- No client-side resizing in the React frontend. The contract between
  frontend and backend is unchanged.
- No change to upload validation (10 MB cap, MIME allow-list).

---

## 3. Design

### 3.1 Conversion rules

Input: raw image bytes plus the original `media_type` (`image/jpeg`,
`image/png`, `image/gif`, `image/webp`).

Output: JPEG bytes plus `media_type = "image/jpeg"`.

Pipeline:

1. Open with Pillow.
2. If the source is animated (multi-frame GIF), keep only the first frame.
3. Apply EXIF orientation via `ImageOps.exif_transpose()`. This is done
   before any other transform — phone photos arrive landscape-on-disk with
   a rotation flag in EXIF, and stripping EXIF without first applying it
   leaves the LLM looking at a sideways picture.
4. If the image has an alpha channel, flatten onto a white background
   (RGBA → RGB).
5. If the longest edge exceeds 1024 px, resize proportionally with the
   Lanczos filter so the longest edge becomes 1024 px. Otherwise keep
   pixel dimensions.
6. Re-encode as JPEG with `quality=85`, `optimize=True`, `progressive=True`.
   No EXIF, no ICC profile in the output.

The re-encode runs even when no resize is needed. This keeps the pipeline
single-path and predictable: callers never have to reason about whether
the bytes they got back are JPEG or something else.

### 3.2 Module layout

A new private module inside the LLM module:

```
backend/modules/llm/
  _image_normaliser.py        ← NEW
```

Public surface (single function):

```python
def normalise_for_llm(data: bytes, media_type: str) -> tuple[bytes, str]:
    """Normalise image bytes for transmission to an upstream LLM.

    Returns (jpeg_bytes, "image/jpeg").
    """
```

The module is private (leading underscore). Other modules import this
function via the LLM module's existing public boundary. The normaliser
itself depends only on Pillow and the standard library.

Pillow is already a dependency in both `pyproject.toml` and
`backend/pyproject.toml`. No new dependency.

### 3.3 Call sites

Three places construct `ContentPart(type="image", data=..., media_type=...)`
or the equivalent base64-string-plus-MIME pair before handing off to an
adapter. Each must call `normalise_for_llm` exactly once, immediately
before base64-encoding:

1. **Chat orchestrator — user attachments.** In
   `backend/modules/chat/_orchestrator.py`, the path that resolves
   `_resolve_attachment_files()` (around line 252) and then builds the
   image content parts (around line 330). Normalise after the file bytes
   are loaded, before base64.
2. **Chat orchestrator — generated images.** Same file, the path added in
   commit `ac463de` that feeds generated-image bytes back into LLM context.
   Normalise the `full` blob before base64.
3. **Vision fallback helper.** `backend/modules/chat/_vision_fallback.py`
   around line 65, where a non-vision model delegates an image-bearing turn
   to a vision-capable helper. Normalise the same way before the helper
   call.

Adapters remain unchanged. `_xai_http.py`, `_mistral_http.py`,
`_nano_gpt_http.py` and `_ollama_http.py` keep their current
`_translate_message()` logic.

### 3.4 Logging

One structured log line per normalisation call, at INFO level:

```
module=llm.image_normaliser
orig_bytes=<int> orig_dims=<w>x<h> orig_media_type=<str>
new_bytes=<int> new_dims=<w>x<h>
duration_ms=<float>
resized=<bool> flattened_alpha=<bool> dropped_frames=<int>
```

This matches the project's claude-oriented logging convention and lets us
verify in production that the pipeline is doing what it should and how
much it is saving.

### 3.5 Error handling

If Pillow cannot decode the bytes (corrupt file, unsupported codec slipped
past upload validation), the normaliser raises a typed exception
`ImageNormalisationError` with the original `media_type` and byte count in
the message. The chat orchestrator catches this, drops that attachment from
the outbound LLM call and emits a recoverable `ErrorEvent` (existing event,
see `shared/events/system.py`) with `error_code = "image_normalisation_failed"`
so the user sees a clear pill in the UI rather than a silent dropout.

We do not retry. If Pillow cannot read it, the bytes are bad.

---

## 4. Data flow

```
upload  →  storage (original kept as-is)
                                  │
                                  ▼
chat orchestrator resolves attachment bytes
                                  │
                                  ▼
            normalise_for_llm(bytes, mime)  ← single chokepoint
                                  │
                                  ▼
                base64 + ContentPart(image)
                                  │
                                  ▼
                LLM adapter (unchanged)
                                  │
                                  ▼
                       upstream provider
```

Generated-image and vision-fallback paths join at the same chokepoint.

---

## 5. Tests

### 5.1 Unit tests

Location: `backend/tests/modules/llm/test_image_normaliser.py` (new file, matches the repo convention).

Pure-function tests — no DB, no async, no fixtures beyond Pillow-generated
in-memory images. Runs on the host without Docker.

- **Large JPEG resizes proportionally.** Input 3000×2000 JPEG → output is
  1024 px on the long edge (1024×683 ± 1), aspect ratio preserved within
  rounding, MIME `image/jpeg`.
- **Small JPEG is re-encoded but not resized.** Input 600×400 JPEG →
  output stays 600×400, MIME `image/jpeg`, byte content differs from input
  (proves re-encoding ran).
- **PNG with alpha is flattened on white.** Input 800×600 RGBA PNG with a
  fully-transparent rectangle → output is 800×600 JPEG; the previously
  transparent pixels read as `(255, 255, 255)` in the output.
- **Animated GIF reduces to one frame.** Input 2-frame animated GIF →
  output decodes as a single-frame JPEG; the log entry shows
  `dropped_frames=1`.
- **EXIF orientation is applied before stripping.** Input portrait photo
  encoded landscape-on-disk with EXIF orientation tag = 6 → output has
  swapped pixel dimensions (the photo is now portrait in pixels) and
  contains no EXIF segment.
- **Output never contains EXIF or ICC profiles.** Verified by re-opening
  the output bytes and asserting `info` is empty of `exif`, `icc_profile`.
- **Corrupt bytes raise `ImageNormalisationError`.** Random non-image
  bytes in → typed exception out, never returns malformed JPEG.

### 5.2 Manual verification

After implementation, run these on the live dev backend with the frontend
attached. Each step is a small thing the developer (Chris) does at the
keyboard and confirms with eyes plus a single backend log line.

1. **Phone photo, large.** Upload a real ~4 MB portrait JPEG from a phone,
   ask "what is this?". Verify the backend log shows a shrink from
   ~4032×3024 to 1024×768 (or similar long-edge=1024), `resized=true`. The
   model's answer must describe the photo in correct orientation, not
   sideways.
2. **Transparent PNG.** Upload a small PNG with real transparency (a saved
   app icon works). Ask "describe this". Answer must be plausible — the
   model should not complain about a strange checkerboard or empty pixels.
   Log shows `flattened_alpha=true`.
3. **Generated image round-trip.** Trigger image generation
   ("draw me a blue flower"). In the next user message ask "what do you
   see in the picture?". Log shows `module=llm.image_normaliser` for the
   generated image being fed back, with the source media-type as PNG and
   output as JPEG. The model's description must match the generated image.
4. **Already-small image.** Upload a 200×200 PNG. Log shows `resized=false`
   but the bytes are still re-encoded as JPEG (`new_bytes` differs from
   `orig_bytes` and output media type is `image/jpeg`).
5. **Log presence.** `grep module=llm.image_normaliser` in the backend log
   for any test session containing image attachments — every LLM call with
   an image should produce exactly one normaliser log line per image part.

If any of these fail, the implementation is not done — even if the unit
tests pass.

---

## 6. Things deliberately not in this spec

- **No frontend changes.** The upload flow stays as-is; the backend
  normalises after receipt.
- **No persistent cache of normalised bytes.** Re-encoding the same image
  across turns is fine on the current VPS (8 cores, Hetzner). If profiling
  later shows it as a real cost, an LRU cache keyed by `(file_id, 1024)`
  can be added in front of the normaliser without touching call sites.
- **No per-adapter overrides.** The 1024 px / JPEG rule is the lowest
  reasonable common denominator and easily within every supported provider's
  capability envelope. A future high-resolution adapter can override by
  bypassing the normaliser, but no current adapter justifies it.
- **No upload-time conversion.** Originals stay on disk so future
  capabilities (download, share, re-process at higher resolution) are not
  blocked.
- **No new MIME types accepted at upload.** Upload validation already
  restricts to JPEG / PNG / GIF / WebP, all of which Pillow handles.

---

## 7. Risk register

- **Pillow decoding failures on weird-but-valid files.** Mitigated by
  catching at the orchestrator boundary and dropping the attachment with a
  user-visible error event rather than failing the whole turn.
- **EXIF rotation regressions.** The unit test for orientation tag = 6
  guards against accidentally moving the EXIF apply step after the strip.
- **Generated image quality loss.** Generated images are usually 1024²
  PNGs that survive a JPEG quality=85 conversion essentially unchanged for
  vision-model purposes. If a future image generator returns much larger
  or fundamentally different formats, the same normaliser still works.
