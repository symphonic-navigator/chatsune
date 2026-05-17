# Nano-GPT Image Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing nano-gpt Premium Provider TTI-capable, exposing Z-Image-Turbo, Z-Image-Base, and Seedream 4.5 via two new image groups (`nano_gpt_zimage`, `nano_gpt_seedream`). As a side effect, refactor the byte-handoff between adapter and `ImageService` so further image providers slot in cleanly.

**Architecture:** New adapter methods on the existing `_nano_gpt_http.py` plus a small `_nano_gpt_image_groups.py` helper module hold the payload builders and Seedream resolution table. The byte buffer that currently lives at module scope on the xAI adapter is replaced by two optional `GeneratedImageResult` fields (`data`, `content_type`) that travel inline through the service, eliminating the cross-module `drain_image_buffer` import.

**Tech Stack:** Python 3.13 / FastAPI / Pydantic v2 / httpx / pytest, plus React 18 / TypeScript / Tailwind / Vite on the frontend.

**Source spec:** [devdocs/specs/2026-05-17-nano-gpt-image-models-design.md](../specs/2026-05-17-nano-gpt-image-models-design.md)

---

## File map

**Backend — modify:**
- `shared/dtos/images.py` — add `data` + `content_type` to `GeneratedImageResult`; add `ZImageConfig`, `SeedreamConfig`; extend `ImageGroupConfig` union.
- `backend/modules/llm/_adapters/_xai_http.py` — write bytes onto result DTO; delete `_LAST_BATCH_BUFFERS`, `drain_image_buffer`.
- `backend/modules/llm/_adapters/_nano_gpt_http.py` — flip `supports_image_generation`; add `image_groups`, `generate_images`, `_build_adapter_router` extension.
- `backend/modules/llm/_adapters/_base.py` — one-line docstring note on the in-process byte-handoff convention.
- `backend/modules/images/_service.py` — read bytes from `item.data` instead of draining the buffer.
- `backend/modules/images/_http.py` — same change in the cockpit-test endpoint.
- `backend/modules/images/_tool_executor.py` — drop the obsolete buffer-comment reference (line 31).
- `backend/tests/modules/llm/adapters/test_xai_http.py` — replace buffer-drain assertions with `item.data` assertions.
- `backend/tests/modules/llm/adapters/test_nano_gpt_http.py` — add image-method tests.
- `tests/modules/images/test_service.py` — drop `drain_image_buffer` monkeypatches; populate `item.data` directly.
- `tests/shared/dtos/test_images.py` — add tests for new fields and configs.

**Backend — create:**
- `backend/modules/llm/_adapters/_nano_gpt_image_groups.py` — group-id constants, payload builders, Seedream resolution table.
- `backend/tests/modules/llm/adapters/test_nano_gpt_image_groups.py` — table-coverage tests, payload builder tests.

**Frontend — modify:**
- `frontend/src/core/api/images.ts` — add `ZImageConfig`, `SeedreamConfig`, extend `ImageGroupConfig` union.
- `frontend/src/features/images/groups/registry.ts` — register both new views.
- `frontend/src/features/images/cockpit/ImageConfigPanel.tsx` — add defaults branches, group-label map, empty-state copy.

**Frontend — create:**
- `frontend/src/features/images/groups/ZImageConfigView.tsx` — model toggle, size dropdown, count stepper.
- `frontend/src/features/images/groups/SeedreamConfigView.tsx` — aspect SegRow, quality SegRow, count stepper.

---

## Task 1: Add `data` + `content_type` fields to `GeneratedImageResult`

**Files:**
- Modify: `shared/dtos/images.py:35-42`
- Test: `tests/shared/dtos/test_images.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/shared/dtos/test_images.py`:

```python
def test_generated_image_result_data_fields_default_none():
    """The in-process handoff fields default to None."""
    r = GeneratedImageResult(id="img_a", width=64, height=32, model_id="m")
    assert r.data is None
    assert r.content_type is None


def test_generated_image_result_excludes_data_from_dump():
    """Bytes never leak through Pydantic serialisation."""
    r = GeneratedImageResult(
        id="img_a", width=64, height=32, model_id="m",
        data=b"raw_bytes", content_type="image/jpeg",
    )
    dumped = r.model_dump()
    assert "data" not in dumped
    assert "content_type" not in dumped
    # Sanity: the existing visible fields are still present.
    assert dumped["id"] == "img_a"
    assert dumped["model_id"] == "m"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/shared/dtos/test_images.py::test_generated_image_result_data_fields_default_none tests/shared/dtos/test_images.py::test_generated_image_result_excludes_data_from_dump -v`

Expected: FAIL — `AttributeError` on `r.data` (field does not exist yet).

- [ ] **Step 3: Add the fields**

Edit `shared/dtos/images.py`, replace the existing `GeneratedImageResult` class:

```python
class GeneratedImageResult(BaseModel):
    kind: Literal["image"] = "image"
    id: str
    width: int
    height: int
    model_id: str
    description: str | None = None  # Phase II hook (vision-derived caption)
    # In-process handoff from adapter to ImageService. Never serialised —
    # the BlobStore is the durable home for image bytes.
    data: bytes | None = Field(default=None, exclude=True)
    content_type: str | None = Field(default=None, exclude=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/shared/dtos/test_images.py -v`

Expected: PASS (all existing tests + the two new ones).

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/images.py tests/shared/dtos/test_images.py
git commit -m "Add in-process byte fields to GeneratedImageResult"
```

---

## Task 2: xAI adapter writes bytes onto the result DTO

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py:64-85, 696-728`
- Test: `backend/tests/modules/llm/adapters/test_xai_http.py:880-896`

- [ ] **Step 1: Update the existing success+moderation test to assert on `item.data`**

In `backend/tests/modules/llm/adapters/test_xai_http.py`, replace the buffer-drain block at the end of `test_xai_generate_images_success_and_moderation_mix` (lines 888-896):

```python
    # The success item carries the bytes inline; the moderated item doesn't.
    assert items[0].data == fake_image_bytes
    assert items[0].content_type == "image/png"
    assert items[1].data is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py::test_xai_generate_images_success_and_moderation_mix -v`

Expected: FAIL — `items[0].data` is `None` because the adapter still writes to the global dict, not to the DTO.

- [ ] **Step 3: Update the adapter to write onto the DTO**

In `backend/modules/llm/_adapters/_xai_http.py`, in `generate_images()` (lines 720-728), replace:

```python
                items.append(GeneratedImageResult(
                    id=image_id,
                    width=width,
                    height=height,
                    model_id=model_id,
                ))
                _LAST_BATCH_BUFFERS[image_id] = (blob_resp.content, content_type)
```

with:

```python
                items.append(GeneratedImageResult(
                    id=image_id,
                    width=width,
                    height=height,
                    model_id=model_id,
                    data=blob_resp.content,
                    content_type=content_type,
                ))
```

Do **not** delete `_LAST_BATCH_BUFFERS` / `drain_image_buffer` yet — Task 5 cleans those up after all callers have been migrated.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_xai_http.py::test_xai_generate_images_success_and_moderation_mix -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py backend/tests/modules/llm/adapters/test_xai_http.py
git commit -m "xAI adapter: attach image bytes inline on result DTO"
```

---

## Task 3: `ImageService` reads bytes from the DTO

**Files:**
- Modify: `backend/modules/images/_service.py:21, 189-213`
- Test: `tests/modules/images/test_service.py:70-114`

- [ ] **Step 1: Update tests to populate `item.data` instead of monkeypatching the drain**

In `tests/modules/images/test_service.py`, update both tests that currently monkeypatch `drain_image_buffer`.

For `test_generate_for_chat_partial_moderation_outcome` (around line 70), replace the success-item construction (line 74) and the monkeypatch block (lines 78-81):

```python
    success = GeneratedImageResult(
        id="img_a", width=1024, height=1024, model_id="grok-imagine-image",
        data=b"raw_bytes", content_type="image/jpeg",
    )
    moderated = ModeratedRejection(reason=None)
    llm.generate_images.return_value = [success, moderated]

    monkeypatch.setattr(
        "backend.modules.images._service.generate_thumbnail_jpeg",
        lambda b, max_edge=256: b"thumb_bytes",
    )
```

(Delete the `drain_image_buffer` monkeypatch entirely; the `generate_thumbnail_jpeg` one stays.)

For `test_generate_for_chat_all_moderated_sets_flag` (around line 101), drop the `drain_image_buffer` monkeypatch (lines 106-109) — moderated items don't go through any byte-read path.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/modules/images/test_service.py::test_generate_for_chat_partial_moderation_outcome tests/modules/images/test_service.py::test_generate_for_chat_all_moderated_sets_flag -v`

Expected: FAIL — the service still calls `drain_image_buffer(item.id)` which now returns `None`, so the success item is treated as moderated.

- [ ] **Step 3: Update `ImageService` to use `item.data` / `item.content_type`**

In `backend/modules/images/_service.py`:

1. Delete the import at line 21:
   ```python
   from backend.modules.llm._adapters._xai_http import drain_image_buffer
   ```

2. Replace the buffer-drain block (around lines 189-213). Find:
   ```python
           # GeneratedImageResult — attempt to drain the adapter's byte buffer.
           assert isinstance(item, GeneratedImageResult)
           buf = drain_image_buffer(item.id)
           if buf is None:
               # Adapter promised a result but no bytes arrived; treat as moderated.
               _log.warning(
                   "image.generate_for_chat user_id=%s image_id=%s "
                   "reason=buffer_empty_treat_as_moderated",
                   user_id, item.id,
               )
               doc = GeneratedImageDocument(
                   id=item.id,
                   user_id=user_id,
                   prompt=prompt,
                   model_id=item.model_id,
                   group_id=active.group_id,
                   connection_id=active.connection_id,
                   config_snapshot=active.config,
                   moderated=True,
                   moderation_reason="adapter returned no bytes",
                   generated_at=datetime.now(UTC),
               )
               docs.append(doc)
               moderated_count += 1
               continue

           full_bytes, content_type = buf
   ```

   Replace with:
   ```python
           # GeneratedImageResult — bytes travel inline on the result DTO.
           assert isinstance(item, GeneratedImageResult)
           if item.data is None or item.content_type is None:
               # Adapter promised a result but no bytes arrived; treat as moderated.
               _log.warning(
                   "image.generate_for_chat user_id=%s image_id=%s "
                   "reason=empty_data_treat_as_moderated",
                   user_id, item.id,
               )
               doc = GeneratedImageDocument(
                   id=item.id,
                   user_id=user_id,
                   prompt=prompt,
                   model_id=item.model_id,
                   group_id=active.group_id,
                   connection_id=active.connection_id,
                   config_snapshot=active.config,
                   moderated=True,
                   moderation_reason="adapter returned no bytes",
                   generated_at=datetime.now(UTC),
               )
               docs.append(doc)
               moderated_count += 1
               continue

           full_bytes, content_type = item.data, item.content_type
   ```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/modules/images/test_service.py -v`

Expected: PASS for all service tests.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/images/_service.py tests/modules/images/test_service.py
git commit -m "ImageService: read image bytes from result DTO"
```

---

## Task 4: `_http.py` test-endpoint reads bytes from the DTO

**Files:**
- Modify: `backend/modules/images/_http.py:147, 175-185`

- [ ] **Step 1: Update the test-endpoint to use `item.data`**

In `backend/modules/images/_http.py`:

1. Delete the import at line 147:
   ```python
   from backend.modules.llm._adapters._xai_http import drain_image_buffer
   ```

2. Replace the loop block (around lines 173-187). Find:
   ```python
       for item in items:
           if isinstance(item, GeneratedImageResult):
               buf = drain_image_buffer(item.id)
               if buf is None:
                   moderated += 1
                   continue
               full_bytes, _ = buf
               try:
                   thumb_bytes = generate_thumbnail_jpeg(full_bytes, max_edge=192)
               except Exception:
                   moderated += 1
                   continue
               data_uri = "data:image/jpeg;base64," + base64.b64encode(thumb_bytes).decode("ascii")
               thumbs_data_uris.append(data_uri)
               successful += 1
           else:
               moderated += 1
   ```

   Replace with:
   ```python
       for item in items:
           if isinstance(item, GeneratedImageResult):
               if item.data is None:
                   moderated += 1
                   continue
               try:
                   thumb_bytes = generate_thumbnail_jpeg(item.data, max_edge=192)
               except Exception:
                   moderated += 1
                   continue
               data_uri = "data:image/jpeg;base64," + base64.b64encode(thumb_bytes).decode("ascii")
               thumbs_data_uris.append(data_uri)
               successful += 1
           else:
               moderated += 1
   ```

- [ ] **Step 2: Run any existing test for the cockpit-test endpoint to verify no regression**

Run: `uv run pytest tests/modules/images/ backend/tests/modules/images/ -v` (whichever directory holds image-related tests; both pass if there's no http-endpoint test yet).

Expected: PASS — no new test added here because the endpoint path is exercised end-to-end through the xAI adapter test in Task 2 (and the nano-gpt adapter test in Task 9).

- [ ] **Step 3: Commit**

```bash
git add backend/modules/images/_http.py
git commit -m "Cockpit test endpoint: read image bytes from result DTO"
```

---

## Task 5: Delete legacy buffer and cleanup remaining xAI tests

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py:64-85, 829-836`
- Modify: `backend/modules/llm/_adapters/_base.py` (docstring note)
- Modify: `backend/modules/llm/_adapters/_xai_http.py:949` (test docstring comment)
- Modify: `backend/modules/images/_tool_executor.py:31`
- Modify: `backend/tests/modules/llm/adapters/test_xai_http.py:1007-1012` (the sub-router test)

- [ ] **Step 1: Delete the buffer state and helper in the xAI adapter**

In `backend/modules/llm/_adapters/_xai_http.py`, remove lines 64-85 (the block starting with `# Module-level temporary buffer…` and including `_LAST_BATCH_BUFFERS`, `_new_image_id` stays, `_probe_dimensions` stays, the `drain_image_buffer` function gets deleted).

Concretely keep only:

```python
def _new_image_id() -> str:
    return f"img_{uuid.uuid4().hex[:12]}"


def _probe_dimensions(image_bytes: bytes) -> tuple[int, int] | None:
    """Return (width, height) from image bytes, or None if unparseable."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            return im.size  # (w, h)
    except Exception:
        return None
```

(i.e. drop the `_LAST_BATCH_BUFFERS` dict and `drain_image_buffer` function entirely.)

- [ ] **Step 2: Remove buffer-drain calls inside the xAI sub-router**

In the `imagine_test` route (around line 829), delete:

```python
        # Drain buffers immediately — bytes are not persisted in the test path.
        for item in items:
            if item.kind == "image":
                drain_image_buffer(item.id)
```

The bytes now live on the DTO; the `_ImagineTestResponse` Pydantic serialisation strips them via `Field(exclude=True)`, so nothing to clean up.

- [ ] **Step 3: Update the obsolete comment in `_tool_executor.py`**

In `backend/modules/images/_tool_executor.py`, around line 31, find any docstring/comment mentioning `_LAST_BATCH_BUFFERS` and update it to describe the new "bytes live on the result DTO" pattern. Most likely a one-line change.

- [ ] **Step 4: Update the residual buffer references in xAI tests**

In `backend/tests/modules/llm/adapters/test_xai_http.py`:

- Around line 949, the docstring says "remain in _LAST_BATCH_BUFFERS after the endpoint response". Reword to: *"…remain attached to the result DTO; sub-router test verifies the bytes are present on items[0].data."*
- Around lines 1007-1012, replace the buffer-drain assertion with an inline-data check. The block:
  ```python
      from backend.modules.llm._adapters._xai_http import drain_image_buffer
      assert drain_image_buffer(item["id"]) is None
  ```
  becomes:
  ```python
      # `data` is excluded from Pydantic serialisation, so the field never
      # appears in the JSON response body. Asserting its absence proves the
      # exclude=True wiring works end-to-end.
      assert "data" not in item
      assert "content_type" not in item
  ```

- [ ] **Step 5: Add the architectural note in `_base.py`**

In `backend/modules/llm/_adapters/_base.py`, find the `generate_images` abstract method docstring (around line 101) and append:

```python
    """Generate images for a single group.

    Image adapters MUST return bytes inline on the result DTO via
    ``GeneratedImageResult.data`` and ``content_type``. Module-level byte
    buffers are forbidden — the inline-on-DTO contract is what lets the
    generic ``ImageService`` accept any adapter without per-adapter imports.
    """
```

(Adjust to match the existing docstring style; the key sentence is the inline-on-DTO rule.)

- [ ] **Step 6: Run the full backend suite**

Run: `uv run pytest backend/tests tests -v -k 'image or xai'`

Expected: PASS across the board. Any failure here is a missed call site — track it down and fix before continuing.

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py \
        backend/modules/llm/_adapters/_base.py \
        backend/modules/images/_tool_executor.py \
        backend/tests/modules/llm/adapters/test_xai_http.py
git commit -m "Delete legacy module-level image byte buffer"
```

---

## Task 6: Add `ZImageConfig` + `SeedreamConfig` to the shared DTOs

**Files:**
- Modify: `shared/dtos/images.py` (imports + new classes + union extension)
- Test: `tests/shared/dtos/test_images.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/shared/dtos/test_images.py`:

```python
from shared.dtos.images import ZImageConfig, SeedreamConfig


def test_zimage_config_defaults():
    cfg = ZImageConfig()
    assert cfg.group_id == "nano_gpt_zimage"
    assert cfg.model == "turbo"
    assert cfg.size == "1024x1024"
    assert cfg.n == 4


def test_zimage_config_size_must_be_known_literal():
    with pytest.raises(ValidationError):
        ZImageConfig(size="999x999")


def test_zimage_config_caps_n_for_base_model():
    """Z-Image-Base is 10x slower; the validator caps n at 4 for Base."""
    cfg = ZImageConfig(model="base", n=10)
    assert cfg.n == 4
    # Turbo keeps its n=10 cap.
    cfg = ZImageConfig(model="turbo", n=10)
    assert cfg.n == 10


def test_seedream_config_defaults():
    cfg = SeedreamConfig()
    assert cfg.group_id == "nano_gpt_seedream"
    assert cfg.aspect == "1:1"
    assert cfg.quality == "standard"
    assert cfg.n == 1


def test_seedream_config_n_capped_at_4():
    with pytest.raises(ValidationError):
        SeedreamConfig(n=5)


def test_image_group_config_union_routes_to_zimage():
    adapter = TypeAdapter(ImageGroupConfig)
    parsed = adapter.validate_python({
        "group_id": "nano_gpt_zimage",
        "model": "base",
        "size": "1536x1536",
        "n": 2,
    })
    assert isinstance(parsed, ZImageConfig)
    assert parsed.size == "1536x1536"


def test_image_group_config_union_routes_to_seedream():
    adapter = TypeAdapter(ImageGroupConfig)
    parsed = adapter.validate_python({
        "group_id": "nano_gpt_seedream",
        "aspect": "16:9",
        "quality": "high",
        "n": 2,
    })
    assert isinstance(parsed, SeedreamConfig)
    assert parsed.aspect == "16:9"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/shared/dtos/test_images.py -v`

Expected: FAIL — `ImportError: cannot import name 'ZImageConfig'`.

- [ ] **Step 3: Add the new configs and extend the union**

In `shared/dtos/images.py`, update the imports at the top:

```python
from pydantic import BaseModel, Field, field_validator, model_validator
```

After the `XaiImagineConfig` class, add:

```python
class ZImageConfig(BaseModel):
    group_id: Literal["nano_gpt_zimage"] = "nano_gpt_zimage"
    model: Literal["turbo", "base"] = "turbo"
    size: Literal[
        "256x256", "512x512", "768x768",
        "1024x1024",
        "1280x720", "720x1280",
        "1536x1024", "1024x1536",
        "1536x1536",
    ] = "1024x1024"
    n: int = Field(4, ge=1, le=10)

    @model_validator(mode="after")
    def _cap_base_n(self) -> "ZImageConfig":
        # Z-Image-Base is ~10x slower than Turbo (43 s vs 4 s at 1024² in the
        # 2026-05-17 spike). Cap n at 4 for Base so the worst-case wait stays
        # under ~3 minutes.
        if self.model == "base" and self.n > 4:
            self.n = 4
        return self


class SeedreamConfig(BaseModel):
    group_id: Literal["nano_gpt_seedream"] = "nano_gpt_seedream"
    aspect: Literal[
        "1:1", "16:9", "9:16",
        "4:3", "3:4",
        "3:2", "2:3",
    ] = "1:1"
    quality: Literal["standard", "high", "ultra"] = "standard"
    n: int = Field(1, ge=1, le=4)
```

Then replace the existing `ImageGroupConfig` annotation:

```python
ImageGroupConfig = Annotated[
    XaiImagineConfig | ZImageConfig | SeedreamConfig,
    Field(discriminator="group_id"),
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/shared/dtos/test_images.py -v`

Expected: PASS for all new tests; existing xAI tests must still pass.

- [ ] **Step 5: Commit**

```bash
git add shared/dtos/images.py tests/shared/dtos/test_images.py
git commit -m "Add ZImageConfig and SeedreamConfig to shared image DTOs"
```

---

## Task 7: Mirror the new types in the frontend

**Files:**
- Modify: `frontend/src/core/api/images.ts`

- [ ] **Step 1: Add the new interface declarations and extend the union**

In `frontend/src/core/api/images.ts`, replace the existing `XaiImagineConfig` + `ImageGroupConfig` block (lines 10-23) with:

```ts
export interface XaiImagineConfig {
  group_id: 'xai_imagine'
  tier: 'normal' | 'quality'
  resolution: '1k' | '2k'
  aspect: '1:1' | '16:9' | '9:16' | '4:3' | '3:4'
  n: number
}

export interface ZImageConfig {
  group_id: 'nano_gpt_zimage'
  model: 'turbo' | 'base'
  size:
    | '256x256' | '512x512' | '768x768'
    | '1024x1024'
    | '1280x720' | '720x1280'
    | '1536x1024' | '1024x1536'
    | '1536x1536'
  n: number
}

export interface SeedreamConfig {
  group_id: 'nano_gpt_seedream'
  aspect: '1:1' | '16:9' | '9:16' | '4:3' | '3:4' | '3:2' | '2:3'
  quality: 'standard' | 'high' | 'ultra'
  n: number
}

/**
 * Discriminated union of all image-group configs.
 * Narrow with: switch (cfg.group_id) { case 'xai_imagine': ... }
 * Extend this union when new image groups are added.
 */
export type ImageGroupConfig = XaiImagineConfig | ZImageConfig | SeedreamConfig
```

- [ ] **Step 2: Type-check the frontend**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean (no errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/core/api/images.ts
git commit -m "Mirror ZImageConfig and SeedreamConfig types on the frontend"
```

---

## Task 8: Create `_nano_gpt_image_groups.py` helper module

**Files:**
- Create: `backend/modules/llm/_adapters/_nano_gpt_image_groups.py`
- Test: `backend/tests/modules/llm/adapters/test_nano_gpt_image_groups.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/modules/llm/adapters/test_nano_gpt_image_groups.py`:

```python
"""Tests for the nano-gpt image groups helper module."""

import pytest

from backend.modules.llm._adapters._nano_gpt_image_groups import (
    SEEDREAM_GROUP_ID,
    SEEDREAM_RESOLUTIONS,
    ZIMAGE_GROUP_ID,
    seedream_payload,
    seedream_resolution,
    zimage_payload,
)
from shared.dtos.images import SeedreamConfig, ZImageConfig


def test_group_id_constants():
    assert ZIMAGE_GROUP_ID == "nano_gpt_zimage"
    assert SEEDREAM_GROUP_ID == "nano_gpt_seedream"


def test_zimage_payload_turbo_1024():
    body = zimage_payload(
        ZImageConfig(model="turbo", size="1024x1024", n=2),
        prompt="a serene landscape",
    )
    assert body == {
        "model": "z-image-turbo",
        "prompt": "a serene landscape",
        "n": 2,
        "size": "1024x1024",
        "response_format": "url",
    }


def test_zimage_payload_base_1536():
    body = zimage_payload(
        ZImageConfig(model="base", size="1536x1536", n=1),
        prompt="x",
    )
    assert body["model"] == "z-image-base"
    assert body["size"] == "1536x1536"


def test_seedream_payload_aspect_to_size():
    body = seedream_payload(
        SeedreamConfig(aspect="16:9", quality="standard", n=1),
        prompt="x",
    )
    assert body["model"] == "seedream-v4.5"
    assert body["size"] == "2560x1440"
    assert body["prompt"] == "x"
    assert body["n"] == 1
    assert body["response_format"] == "url"


def test_seedream_resolution_table_covers_all_cells():
    """Every aspect × quality cell must be present and satisfy constraints."""
    aspects = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]
    qualities = ["standard", "high", "ultra"]
    assert len(SEEDREAM_RESOLUTIONS) == len(aspects) * len(qualities)
    for aspect in aspects:
        for quality in qualities:
            w, h = seedream_resolution(aspect, quality)
            # Nano-gpt's documented minimum.
            assert w * h >= 3_686_400, f"{aspect}/{quality} = {w}x{h} below min"
            # Diffusion models prefer multiples of 32.
            assert w % 32 == 0, f"{aspect}/{quality}: width {w} not /32"
            assert h % 32 == 0, f"{aspect}/{quality}: height {h} not /32"
            # Aspect roughly preserved (±5 %).
            expected_w, expected_h = aspect.split(":")
            ideal_ratio = int(expected_w) / int(expected_h)
            actual_ratio = w / h
            assert abs(actual_ratio - ideal_ratio) / ideal_ratio < 0.05, \
                f"{aspect}/{quality}: ratio {actual_ratio:.3f} vs ideal {ideal_ratio:.3f}"


def test_seedream_resolution_unknown_aspect_raises():
    with pytest.raises(KeyError):
        seedream_resolution("21:9", "standard")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_image_groups.py -v`

Expected: FAIL — module does not exist yet.

- [ ] **Step 3: Create the helper module**

Create `backend/modules/llm/_adapters/_nano_gpt_image_groups.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_image_groups.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_nano_gpt_image_groups.py \
        backend/tests/modules/llm/adapters/test_nano_gpt_image_groups.py
git commit -m "Add nano-gpt image groups helper with payload builders"
```

---

## Task 9: Wire nano-gpt adapter for image generation

**Files:**
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py` (imports, class attrs, two new methods)
- Test: `backend/tests/modules/llm/adapters/test_nano_gpt_http.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/modules/llm/adapters/test_nano_gpt_http.py` (or create if no test file exists yet — match the surrounding test style):

```python
import io
import pytest
from PIL import Image

from backend.modules.llm._adapters._nano_gpt_http import NanoGptHttpAdapter
from backend.modules.llm._adapters._nano_gpt_image_groups import (
    SEEDREAM_GROUP_ID,
    ZIMAGE_GROUP_ID,
)
from backend.modules.llm._adapters._types import ResolvedConnection
from shared.dtos.images import (
    GeneratedImageResult,
    SeedreamConfig,
    ZImageConfig,
)


def _resolved_nano_conn() -> ResolvedConnection:
    return ResolvedConnection(
        id="conn_nano",
        user_id="u1",
        slug="nano",
        display_name="nano-gpt",
        adapter_type="nano_gpt_http",
        config={"url": "https://nano-gpt.com/api/v1", "api_key": "sk-test"},
    )


def _fake_image_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 32), (10, 20, 30)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_nano_gpt_supports_image_generation_flag():
    assert NanoGptHttpAdapter.supports_image_generation is True


@pytest.mark.asyncio
async def test_nano_gpt_image_groups_returns_both_groups():
    adapter = NanoGptHttpAdapter()
    groups = await adapter.image_groups(_resolved_nano_conn())
    assert set(groups) == {ZIMAGE_GROUP_ID, SEEDREAM_GROUP_ID}


@pytest.mark.asyncio
async def test_nano_gpt_generate_images_zimage_attaches_bytes(monkeypatch):
    fake_bytes = _fake_image_bytes()
    fake_resp_json = {
        "created": 1,
        "requestId": "req_abc",
        "data": [{"storageKey": "k", "url": "https://r2.example/img.jpg"}],
        "cost": 0.017,
    }

    class _Resp:
        def __init__(self, status=200, content=b"", json_data=None, headers=None):
            self.status_code = status
            self.content = content
            self._json = json_data
            self.headers = headers or {}
            self.text = ""

        def json(self):
            return self._json

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, *a, **kw):
            assert url.endswith("/images/generations")
            return _Resp(json_data=fake_resp_json)

        async def get(self, url, *a, **kw):
            # Must NOT carry the Authorization header.
            headers = kw.get("headers") or {}
            assert "Authorization" not in headers, (
                "Cloudflare R2 signed URL must be fetched without bearer auth"
            )
            return _Resp(
                content=fake_bytes,
                headers={"content-type": "image/jpeg"},
            )

    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http.httpx.AsyncClient",
        _FakeClient,
    )

    adapter = NanoGptHttpAdapter()
    items = await adapter.generate_images(
        connection=_resolved_nano_conn(),
        group_id=ZIMAGE_GROUP_ID,
        config=ZImageConfig(model="turbo", size="1024x1024", n=1),
        prompt="a serene landscape",
    )

    assert len(items) == 1
    assert isinstance(items[0], GeneratedImageResult)
    assert items[0].data == fake_bytes
    assert items[0].content_type == "image/jpeg"
    assert items[0].model_id == "z-image-turbo"
    assert items[0].width == 64
    assert items[0].height == 32


@pytest.mark.asyncio
async def test_nano_gpt_generate_images_seedream_attaches_bytes(monkeypatch):
    fake_bytes = _fake_image_bytes()
    fake_resp_json = {
        "created": 1,
        "requestId": "req_xyz",
        "data": [{"storageKey": "k", "url": "https://r2.example/img.jpg"}],
        "cost": 0.04,
    }

    captured_body = {}

    class _Resp:
        def __init__(self, status=200, content=b"", json_data=None, headers=None):
            self.status_code = status
            self.content = content
            self._json = json_data
            self.headers = headers or {}
            self.text = ""

        def json(self):
            return self._json

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def post(self, url, *a, **kw):
            captured_body.update(kw.get("json") or {})
            return _Resp(json_data=fake_resp_json)

        async def get(self, url, *a, **kw):
            return _Resp(
                content=fake_bytes,
                headers={"content-type": "image/jpeg"},
            )

    monkeypatch.setattr(
        "backend.modules.llm._adapters._nano_gpt_http.httpx.AsyncClient",
        _FakeClient,
    )

    adapter = NanoGptHttpAdapter()
    items = await adapter.generate_images(
        connection=_resolved_nano_conn(),
        group_id=SEEDREAM_GROUP_ID,
        config=SeedreamConfig(aspect="16:9", quality="standard", n=1),
        prompt="a city skyline at night",
    )

    assert len(items) == 1
    assert items[0].model_id == "seedream-v4.5"
    # Seedream sends "size: WxH" derived from the resolution table.
    assert captured_body.get("size") == "2560x1440"


@pytest.mark.asyncio
async def test_nano_gpt_generate_images_unknown_group_raises():
    adapter = NanoGptHttpAdapter()
    with pytest.raises(ValueError, match="unknown image group"):
        await adapter.generate_images(
            connection=_resolved_nano_conn(),
            group_id="bogus_group",
            config=ZImageConfig(),
            prompt="x",
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v -k 'image_generation or image_groups or zimage or seedream or unknown_group'`

Expected: FAIL — adapter does not yet declare the flag or implement the methods.

- [ ] **Step 3: Wire the adapter**

In `backend/modules/llm/_adapters/_nano_gpt_http.py`:

1. Add imports near the other imports at the top of the file:

   ```python
   import io
   import uuid
   from typing import ClassVar
   from PIL import Image

   from backend.modules.llm._adapters._nano_gpt_image_groups import (
       SEEDREAM_GROUP_ID,
       ZIMAGE_GROUP_ID,
       seedream_payload,
       zimage_payload,
   )
   from shared.dtos.images import (
       GeneratedImageResult,
       ImageGenItem,
       ImageGroupConfig,
       ModeratedRejection,
       SeedreamConfig,
       ZImageConfig,
   )
   ```

2. Inside the `NanoGptHttpAdapter` class (alongside `adapter_type`, `display_name`, etc.), add:

   ```python
   supports_image_generation: ClassVar[bool] = True
   ```

3. Add two new methods on the class (alongside the existing ones — placement near `stream_completion` is fine; keeping image-related code grouped helps later readers):

   ```python
   async def image_groups(self, connection: ResolvedConnection) -> list[str]:
       return [ZIMAGE_GROUP_ID, SEEDREAM_GROUP_ID]

   async def generate_images(
       self,
       connection: ResolvedConnection,
       group_id: str,
       config: ImageGroupConfig,
       prompt: str,
   ) -> list[ImageGenItem]:
       if group_id == ZIMAGE_GROUP_ID:
           if not isinstance(config, ZImageConfig):
               raise ValueError(
                   f"expected ZImageConfig, got {type(config).__name__}"
               )
           body = zimage_payload(config, prompt)
           model_id = body["model"]
       elif group_id == SEEDREAM_GROUP_ID:
           if not isinstance(config, SeedreamConfig):
               raise ValueError(
                   f"expected SeedreamConfig, got {type(config).__name__}"
               )
           body = seedream_payload(config, prompt)
           model_id = body["model"]
       else:
           raise ValueError(
               f"unknown image group {group_id!r} for nano-gpt adapter"
           )

       base_url = connection.config["url"].rstrip("/")
       api_key = connection.config.get("api_key") or ""
       headers = {
           "Authorization": f"Bearer {api_key}",
           "Content-Type": "application/json",
       }

       async with httpx.AsyncClient(timeout=120.0) as client:
           resp = await client.post(
               f"{base_url}/images/generations",
               headers=headers, json=body,
           )
           if resp.status_code >= 400:
               _log.error(
                   "nano_gpt.generate_images failed status=%d body=%s",
                   resp.status_code, resp.text[:500],
               )
               raise RuntimeError(
                   f"nano-gpt image generation failed: "
                   f"{resp.status_code} {resp.text[:200]}"
               )
           payload = resp.json()
           cost = payload.get("cost")
           if cost is not None:
               _log.debug("nano_gpt.generate_images cost_usd=%s", cost)

           items: list[ImageGenItem] = []
           for entry in payload.get("data", []):
               image_url = entry.get("url") if isinstance(entry, dict) else None
               if not image_url:
                   items.append(ModeratedRejection(reason="no_url"))
                   continue

               # IMPORTANT: nano-gpt returns Cloudflare R2 signed URLs;
               # sending the Bearer header collides with the AWS-V4
               # signature, so we issue a bare GET on a fresh client.
               async with httpx.AsyncClient(timeout=60.0) as blob_client:
                   blob_resp = await blob_client.get(image_url)
                   if blob_resp.status_code >= 400:
                       items.append(ModeratedRejection(reason="fetch_failed"))
                       continue
                   content_type = blob_resp.headers.get(
                       "content-type", "image/jpeg",
                   )
                   dims = _probe_dimensions(blob_resp.content)
                   width, height = dims if dims else (0, 0)
                   image_id = f"img_{uuid.uuid4().hex[:12]}"
                   items.append(GeneratedImageResult(
                       id=image_id,
                       width=width,
                       height=height,
                       model_id=model_id,
                       data=blob_resp.content,
                       content_type=content_type,
                   ))
       return items
   ```

4. Add the `_probe_dimensions` helper at module scope if it does not exist already (the xAI adapter has one; we keep a copy here so the modules stay independent):

   ```python
   def _probe_dimensions(image_bytes: bytes) -> tuple[int, int] | None:
       try:
           with Image.open(io.BytesIO(image_bytes)) as im:
               return im.size
       except Exception:
           return None
   ```

   Place near the other module-level helpers.

5. Verify the `_log` module logger already exists (it does, line 87 of the existing file).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v`

Expected: PASS for the new tests; existing nano-gpt tests must still pass.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_nano_gpt_http.py \
        backend/tests/modules/llm/adapters/test_nano_gpt_http.py
git commit -m "nano-gpt adapter: image_groups and generate_images"
```

---

## Task 10: Add the `/imagine/test` sub-router to the nano-gpt adapter

**Files:**
- Modify: `backend/modules/llm/_adapters/_nano_gpt_http.py` (add `router()` classmethod and `_build_adapter_router()`)

**Note:** The nano-gpt adapter currently has **no** sub-router (unlike xAI/Ollama/Tensorix/OpenRouter, which all do). The router-mounting machinery in `backend/modules/llm/_handlers.py:356-381` already iterates every adapter class and mounts whatever `cls.router()` returns; adding the method here is enough to wire it up.

- [ ] **Step 1: Add the `router()` classmethod on `NanoGptHttpAdapter`**

In `backend/modules/llm/_adapters/_nano_gpt_http.py`, inside the `NanoGptHttpAdapter` class (next to `templates()` / `config_schema()` around line 633-649), add:

```python
    @classmethod
    def router(cls) -> APIRouter:
        return _build_adapter_router()
```

Add the `APIRouter` import at the top of the file (alongside the other `fastapi` imports if present; if no `fastapi` import exists yet, add `from fastapi import APIRouter, Depends, HTTPException`).

- [ ] **Step 2: Add the `_build_adapter_router()` function at module scope**

At the bottom of `backend/modules/llm/_adapters/_nano_gpt_http.py` (after the class body), add:

```python
def _build_adapter_router() -> APIRouter:
    from pydantic import BaseModel, TypeAdapter
    from backend.modules.llm._resolver import resolve_connection_for_user
    from shared.dtos.images import ImageGenItem, ImageGroupConfig

    router = APIRouter()

    class _ImagineTestRequest(BaseModel):
        group_id: str
        config: dict
        prompt: str = "a serene mountain landscape at dawn"

    class _ImagineTestResponse(BaseModel):
        items: list[ImageGenItem]

    @router.post("/imagine/test", response_model=_ImagineTestResponse)
    async def imagine_test(
        body: _ImagineTestRequest,
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> _ImagineTestResponse:
        _log.info(
            "nano_gpt.imagine_test connection_id=%s group_id=%s",
            c.id, body.group_id,
        )
        try:
            cfg = TypeAdapter(ImageGroupConfig).validate_python(
                {**body.config, "group_id": body.group_id}
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"invalid config: {exc}")

        adapter = NanoGptHttpAdapter()
        items = await adapter.generate_images(
            connection=c,
            group_id=body.group_id,
            config=cfg,
            prompt=body.prompt,
        )
        return _ImagineTestResponse(items=items)

    return router
```

Local imports inside the function keep the module light at import time (mirrors what xAI does at `_xai_http.py:753-803`).

- [ ] **Step 3: Verify the router is mounted at startup**

Run: `uv run python -c "from backend.main import app; print([r.path for r in app.routes if 'nano' in r.path or 'imagine' in r.path])"`

Expected: the output includes a path like `/api/llm/connections/{id}/adapter/imagine/test` (the exact prefix depends on the mounting code in `_handlers.py`).

- [ ] **Step 4: Run the nano-gpt adapter tests**

Run: `uv run pytest backend/tests/modules/llm/adapters/test_nano_gpt_http.py -v`

Expected: PASS — adding the router should not break any existing test. The route itself is covered indirectly via Task 9's `generate_images` tests; a dedicated HTTP-level test is left to the manual QA pass in Task 14, which exercises the "Test image" button against the live API.

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/_adapters/_nano_gpt_http.py
git commit -m "nano-gpt adapter: add /imagine/test sub-router"
```

---

## Task 11: Create `ZImageConfigView`

**Files:**
- Create: `frontend/src/features/images/groups/ZImageConfigView.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/features/images/groups/ZImageConfigView.tsx`:

```tsx
import type { ZImageConfig } from '@/core/api/images'
import type { ConfigViewProps } from './registry'

const MODELS: ZImageConfig['model'][] = ['turbo', 'base']
const SIZES: ZImageConfig['size'][] = [
  '256x256',
  '512x512',
  '768x768',
  '1024x1024',
  '1280x720',
  '720x1280',
  '1536x1024',
  '1024x1536',
  '1536x1536',
]

/** Option style applied to native <select> options — see CLAUDE.md. */
const OPTION_STYLE: React.CSSProperties = {
  background: '#0f0d16',
  color: 'rgba(255,255,255,0.85)',
}

// --- internal primitives -----------------------------------------------------

type SegRowProps<T extends string> = {
  label: string
  options: T[]
  value: T
  onChange: (v: T) => void
}

function SegRow<T extends string>({ label, options, value, onChange }: SegRowProps<T>) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[11px] text-white/50 shrink-0">{label}</span>
      <div className="flex gap-1">
        {options.map((opt) => (
          <button
            key={opt}
            type="button"
            onClick={() => onChange(opt)}
            className={[
              'px-2 py-0.5 rounded text-[11px] font-mono border transition',
              value === opt
                ? 'border-[#c084fc]/60 bg-[#c084fc]/20 text-[#c084fc]'
                : 'border-white/10 bg-white/5 text-white/50 hover:bg-white/10 hover:text-white/75',
            ].join(' ')}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  )
}

type StepperProps = {
  label: string
  value: number
  min: number
  max: number
  onChange: (v: number) => void
}

function Stepper({ label, value, min, max, onChange }: StepperProps) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[11px] text-white/50 shrink-0">{label}</span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={value <= min}
          onClick={() => onChange(Math.max(min, value - 1))}
          className="w-6 h-6 flex items-center justify-center rounded border border-white/10 bg-white/5 text-white/60 hover:bg-white/15 disabled:opacity-30 disabled:cursor-not-allowed text-sm leading-none transition"
          aria-label="Decrease"
        >
          −
        </button>
        <span className="w-5 text-center text-[12px] font-mono text-white/85">{value}</span>
        <button
          type="button"
          disabled={value >= max}
          onClick={() => onChange(Math.min(max, value + 1))}
          className="w-6 h-6 flex items-center justify-center rounded border border-white/10 bg-white/5 text-white/60 hover:bg-white/15 disabled:opacity-30 disabled:cursor-not-allowed text-sm leading-none transition"
          aria-label="Increase"
        >
          +
        </button>
      </div>
    </div>
  )
}

// --- public view -------------------------------------------------------------

export function ZImageConfigView({ config, onChange }: ConfigViewProps<ZImageConfig>) {
  // Base is ~10× slower than Turbo; the backend caps n at 4 for Base. Mirror
  // that cap in the UI so the Stepper doesn't let users dial in a value the
  // server will silently clamp.
  const nMax = config.model === 'base' ? 4 : 10
  const clampedN = Math.min(config.n, nMax)

  return (
    <div className="space-y-2">
      <SegRow
        label="Model"
        options={MODELS}
        value={config.model}
        onChange={(model) => {
          const nextN = model === 'base' ? Math.min(config.n, 4) : config.n
          onChange({ ...config, model, n: nextN })
        }}
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-[11px] text-white/50 shrink-0">Size</span>
        <select
          value={config.size}
          onChange={(e) => onChange({ ...config, size: e.target.value as ZImageConfig['size'] })}
          className="text-[11px] bg-[#1a1625] border border-white/15 rounded px-2 py-1 text-white/85 focus:outline-none focus:border-[#c084fc]/50 font-mono"
        >
          {SIZES.map((s) => (
            <option key={s} value={s} style={OPTION_STYLE}>{s}</option>
          ))}
        </select>
      </div>
      <Stepper
        label="Count"
        value={clampedN}
        min={1}
        max={nMax}
        onChange={(n) => onChange({ ...config, n })}
      />
    </div>
  )
}
```

- [ ] **Step 2: Type-check the frontend**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/images/groups/ZImageConfigView.tsx
git commit -m "Add ZImageConfigView component"
```

---

## Task 12: Create `SeedreamConfigView`

**Files:**
- Create: `frontend/src/features/images/groups/SeedreamConfigView.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/features/images/groups/SeedreamConfigView.tsx`:

```tsx
import type { SeedreamConfig } from '@/core/api/images'
import type { ConfigViewProps } from './registry'

const ASPECTS: SeedreamConfig['aspect'][] = ['1:1', '16:9', '9:16', '4:3', '3:4', '3:2', '2:3']
const QUALITIES: SeedreamConfig['quality'][] = ['standard', 'high', 'ultra']

// Reuse the same primitives shape as XaiImagineConfigView. Kept inline rather
// than extracted to a shared module — three identical SegRow/Stepper copies
// across the three views is cheaper to read than a layer of abstraction.

type SegRowProps<T extends string> = {
  label: string
  options: T[]
  value: T
  onChange: (v: T) => void
}

function SegRow<T extends string>({ label, options, value, onChange }: SegRowProps<T>) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[11px] text-white/50 shrink-0">{label}</span>
      <div className="flex gap-1 flex-wrap justify-end">
        {options.map((opt) => (
          <button
            key={opt}
            type="button"
            onClick={() => onChange(opt)}
            className={[
              'px-2 py-0.5 rounded text-[11px] font-mono border transition',
              value === opt
                ? 'border-[#c084fc]/60 bg-[#c084fc]/20 text-[#c084fc]'
                : 'border-white/10 bg-white/5 text-white/50 hover:bg-white/10 hover:text-white/75',
            ].join(' ')}
          >
            {opt}
          </button>
        ))}
      </div>
    </div>
  )
}

type StepperProps = {
  label: string
  value: number
  min: number
  max: number
  onChange: (v: number) => void
}

function Stepper({ label, value, min, max, onChange }: StepperProps) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-[11px] text-white/50 shrink-0">{label}</span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          disabled={value <= min}
          onClick={() => onChange(Math.max(min, value - 1))}
          className="w-6 h-6 flex items-center justify-center rounded border border-white/10 bg-white/5 text-white/60 hover:bg-white/15 disabled:opacity-30 disabled:cursor-not-allowed text-sm leading-none transition"
          aria-label="Decrease"
        >
          −
        </button>
        <span className="w-5 text-center text-[12px] font-mono text-white/85">{value}</span>
        <button
          type="button"
          disabled={value >= max}
          onClick={() => onChange(Math.min(max, value + 1))}
          className="w-6 h-6 flex items-center justify-center rounded border border-white/10 bg-white/5 text-white/60 hover:bg-white/15 disabled:opacity-30 disabled:cursor-not-allowed text-sm leading-none transition"
          aria-label="Increase"
        >
          +
        </button>
      </div>
    </div>
  )
}

// --- public view -------------------------------------------------------------

export function SeedreamConfigView({ config, onChange }: ConfigViewProps<SeedreamConfig>) {
  return (
    <div className="space-y-2">
      <SegRow
        label="Aspect"
        options={ASPECTS}
        value={config.aspect}
        onChange={(aspect) => onChange({ ...config, aspect })}
      />
      <SegRow
        label="Quality"
        options={QUALITIES}
        value={config.quality}
        onChange={(quality) => onChange({ ...config, quality })}
      />
      <Stepper
        label="Count"
        value={config.n}
        min={1}
        max={4}
        onChange={(n) => onChange({ ...config, n })}
      />
    </div>
  )
}
```

- [ ] **Step 2: Type-check the frontend**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/images/groups/SeedreamConfigView.tsx
git commit -m "Add SeedreamConfigView component"
```

---

## Task 13: Wire the new views into the cockpit

**Files:**
- Modify: `frontend/src/features/images/groups/registry.ts`
- Modify: `frontend/src/features/images/cockpit/ImageConfigPanel.tsx`

- [ ] **Step 1: Register both new views**

Replace the contents of `frontend/src/features/images/groups/registry.ts`:

```ts
import type { ImageGroupConfig } from '@/core/api/images'
import type { ComponentType } from 'react'
import { XaiImagineConfigView } from './XaiImagineConfigView'
import { ZImageConfigView } from './ZImageConfigView'
import { SeedreamConfigView } from './SeedreamConfigView'

export type ConfigViewProps<T extends ImageGroupConfig> = {
  config: T
  onChange: (next: T) => void
}

export type ConfigViewComponent = ComponentType<ConfigViewProps<ImageGroupConfig>>

/**
 * Map of group_id → config-view component.
 */
export const IMAGE_GROUP_VIEWS: Partial<Record<string, ConfigViewComponent>> = {
  xai_imagine: XaiImagineConfigView as ConfigViewComponent,
  nano_gpt_zimage: ZImageConfigView as ConfigViewComponent,
  nano_gpt_seedream: SeedreamConfigView as ConfigViewComponent,
}
```

- [ ] **Step 2: Extend the panel's defaults, labels, and empty state**

In `frontend/src/features/images/cockpit/ImageConfigPanel.tsx`:

1. Replace the `defaultConfigForGroup` helper (around lines 16-20) with:

   ```ts
   function defaultConfigForGroup(groupId: string): ImageGroupConfig {
     if (groupId === 'nano_gpt_zimage') {
       return { group_id: 'nano_gpt_zimage', model: 'turbo', size: '1024x1024', n: 4 }
     }
     if (groupId === 'nano_gpt_seedream') {
       return { group_id: 'nano_gpt_seedream', aspect: '1:1', quality: 'standard', n: 1 }
     }
     // xai_imagine and last-resort fallback share the same default.
     return { ...XAI_IMAGINE_DEFAULTS }
   }
   ```

2. Replace the `groupLabel` helper (around lines 23-25) with:

   ```ts
   const GROUP_LABELS: Record<string, string> = {
     xai_imagine: 'Grok Imagine',
     nano_gpt_zimage: 'Z-Image',
     nano_gpt_seedream: 'Seedream 4.5',
   }
   function groupLabel(groupId: string): string {
     return GROUP_LABELS[groupId] ?? groupId.replace(/_/g, ' ')
   }
   ```

3. Replace the `EmptyState` component's text (around lines 35-42) with:

   ```tsx
   function EmptyState() {
     return (
       <p className="text-xs text-white/50 leading-relaxed">
         No image-capable connection configured.{' '}
         <span className="text-white/70">Add an xAI or nano-gpt connection in settings.</span>
       </p>
     )
   }
   ```

4. Hydration fallback at lines 96-99 — the `firstGroup ?? 'xai_imagine'` literal stays as a sane fallback, but the comment can be updated:

   ```ts
   // Prefer the connection's first declared group; fall back to xai_imagine
   // only if the connection is somehow empty (defensive, should not happen).
   const firstGroup = first.group_ids[0] ?? 'xai_imagine'
   ```

- [ ] **Step 3: Type-check and build the frontend**

Run: `cd frontend && pnpm tsc --noEmit && pnpm run build`

Expected: clean type-check; successful build.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/images/groups/registry.ts \
        frontend/src/features/images/cockpit/ImageConfigPanel.tsx
git commit -m "Wire ZImage and Seedream views into the image cockpit"
```

---

## Task 14: Manual QA pass against the live nano-gpt account

**Files:** none — pure smoke test.

- [ ] **Step 1: Start the dev stack**

```bash
docker compose up -d mongo redis
uv run uvicorn backend.main:app --reload
# in a second terminal:
cd frontend && pnpm run dev
```

- [ ] **Step 2: Connect nano-gpt as a Premium Provider**

In the UI:
1. Open Settings → Premium Providers.
2. Connect "nano-gpt" using a real API key (or paste from `.nano-test-key` for the QA pass).
3. Confirm the test-connection round-trip succeeds.

- [ ] **Step 3: Verify the cockpit lists both connections**

1. Open the image cockpit. Confirm the **Connection** field is now a `<select>` containing both xAI and nano-gpt.
2. Pick nano-gpt. The **Group** field should show two options (`Z-Image`, `Seedream 4.5`).

- [ ] **Step 4: Test Z-Image-Turbo**

1. Group → Z-Image. Model → Turbo. Size → 1024×1024. Count → 1.
2. Click **Test image**. Expected: a thumbnail appears within ~5 s.

- [ ] **Step 5: Test Z-Image-Base**

1. Same group, switch Model → Base. Confirm Count auto-clamps to 4 (was 10).
2. Click **Test image**. Expected: thumbnail in ~45 s. Patience is the test.

- [ ] **Step 6: Test Seedream**

1. Group → Seedream 4.5. Aspect → 1:1. Quality → Standard. Count → 1.
2. Click **Test image**. Expected: thumbnail in ~20 s.
3. Switch Aspect → 16:9 and confirm a new image with the expected aspect.

- [ ] **Step 7: End-to-end through a chat session**

1. Open or start a chat. Ask the model to generate an image (e.g. "draw me a sunset over mountains").
2. Confirm the image appears inline under the assistant message.
3. Open the gallery. Confirm the image is listed there with correct dimensions and the right `model_id`.

- [ ] **Step 8: Switch back to xAI mid-session to verify the buffer refactor**

1. With at least one xAI image already generated previously (or generate one now), confirm the old image still renders correctly from the gallery — i.e. nothing was lost during the byte-handoff refactor.

- [ ] **Step 9: Commit any UI tweaks that came out of QA**

If the manual pass reveals UI quirks (label widths, spinner copy, etc.), fix inline and:

```bash
git add <touched files>
git commit -m "Cockpit polish from nano-gpt QA pass"
```

---

## Wrap-up

When all 14 tasks pass:

```bash
git log --oneline master..HEAD
# Should show ~14 commits, each scoped to one task.
```

The full backend suite must pass: `uv run pytest backend/tests tests -v`.
The full frontend build must succeed: `cd frontend && pnpm run build`.

Per CLAUDE.md, this branch then merges to master.
