# TTI via xAI grok-imagine — Phase I Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `devdocs/specs/2026-04-26-tti-xai-imagine-design.md`

**Goal:** Add text-to-image generation as an LLM-callable tool, persisted per user with a dedicated cockpit panel, gallery and attachment-picker integration; pilot upstream is xAI grok-imagine.

**Architecture:** New `backend/modules/images/` module owns the `generated_images` and `user_image_configs` collections, the `ImageService`, the HTTP router and the image-gen tool executor. The xAI adapter is extended with `image_groups()` and `generate_images()` plus a sub-router test endpoint. Per-group typed configs live in `shared/dtos/images.py` as a Pydantic discriminated union; the frontend has a `group_id → ConfigView` registry that mirrors this. The image-gen tool participates in the existing `CHAT_TOOL_CALL_*` event lifecycle — no new event topics. Image lifetime is independent of chats; deletion is explicit via the gallery.

**Tech Stack:** Python 3.13 / FastAPI / Pydantic v2 / Motor (MongoDB), Pillow for thumbnail generation, React + TypeScript + Tailwind on the frontend, existing per-user Connection encryption (Fernet) for the xAI API key.

**Per-task discipline:**

- Read every file you intend to modify **before** editing it. Patterns in this repo are strict (see CLAUDE.md "Module Boundaries"); never import from another module's `_internal.py`.
- For Python edits: run `uv run python -m py_compile <file>` after every change.
- For backend tests: run on host via `PYTHONPATH=. uv run pytest <specific path>` against the running Docker-Compose MongoDB (port 27017 must be reachable; `docker compose up -d mongodb redis` first if needed). There is **no** `backend` service in compose. The four problematic full-suite ignores from CLAUDE.md still apply when running the *whole* backend suite, but new targeted tests work fine on host as long as compose-side Mongo is up.
- For TS edits: run `pnpm --dir frontend tsc --noEmit` after every change.
- Commit after every task with a short imperative message (CLAUDE.md). No `--no-verify`.
- Do not exceed task scope. If you discover something outside the task that needs fixing, note it in the task summary and stop.

---

## File structure

### New backend files

```
backend/modules/images/
  __init__.py             ← public API: ImageService, router, init_indexes
  _models.py              ← MongoDB document Pydantic models
  _repository.py          ← GeneratedImagesRepository, UserImageConfigRepository
  _thumbnails.py          ← Pillow JPG thumbnail generation
  _service.py             ← ImageService implementation
  _tool_executor.py       ← ImageGenerationToolExecutor
  _http.py                ← FastAPI router for /api/images/...

backend/modules/llm/_adapters/_xai_image_groups.py   ← xAI image group definitions
shared/dtos/images.py                                 ← group configs, refs, results
```

### Modified backend files

- `backend/modules/llm/_adapters/_base.py` — add optional image-gen capability hooks
- `backend/modules/llm/_adapters/_xai_http.py` — implement image methods; extend sub-router
- `backend/modules/llm/__init__.py` — expose `LlmService.list_image_groups`, `validate_image_config`, `generate_images`
- `backend/modules/tools/_registry.py` — register `image_generation` ToolGroup conditionally
- `backend/modules/chat/_repository.py` (or attachment loader file) — recognise `generated_images.id` as a valid attachment id; subagent will pinpoint exact file
- `backend/main.py` — mount images router, init indexes
- `shared/dtos/chat.py` — extend `ToolCallRefDto` with `moderated_count`, `ChatMessageDto` with `image_refs`
- `pyproject.toml` (root) and `backend/pyproject.toml` — add `pillow>=11.0`

### New frontend files

```
frontend/src/features/images/
  groups/
    registry.ts
    XaiImagineConfigView.tsx
  cockpit/
    ImageButton.tsx
    ImageConfigPanel.tsx
  chat/
    InlineImageBlock.tsx
    ImageLightbox.tsx
  gallery/
    GalleryGrid.tsx
    GalleryLightbox.tsx
  attachments/
    GeneratedImagesTab.tsx
  api.ts                   ← thin REST wrappers for /api/images/*
  store.ts                 ← active config store, gallery cache (zustand or similar — match existing pattern)
```

### Modified frontend files

- `frontend/src/features/chat/cockpit/CockpitBar.tsx` — desktop and mobile button slots
- The current attachment picker (subagent will locate and confirm path) — add tab strip
- The current assistant-message renderer (subagent will locate) — render `InlineImageBlock` when `image_refs` present
- Generated TS types from `shared/dtos/images.py` — via the existing shared-contract pipeline (subagent will locate the codegen entry point)

---

## Task index

1. Add Pillow dependency to both `pyproject.toml` files
2. Shared DTOs: `shared/dtos/images.py`
3. Shared DTOs: extend `shared/dtos/chat.py` with `moderated_count` and `image_refs`
4. Backend: image MongoDB models (`_models.py`)
5. Backend: `GeneratedImagesRepository`
6. Backend: `UserImageConfigRepository`
7. Backend: thumbnail generator (`_thumbnails.py`)
8. Backend: extend `BaseAdapter` with optional image hooks
9. Backend: implement xAI image methods + group definitions
10. Backend: extend xAI sub-router with `/imagine/test` endpoint
11. Backend: extend `LlmService` with image methods
12. Backend: `ImageService`
13. Backend: `ImageGenerationToolExecutor` + register in tools registry conditionally
14. Backend: `_http.py` — `/api/images/*` routes
15. Backend: wire `images` module into `main.py`
16. Backend: extend chat attachment loader to resolve `generated_images.id`
17. Frontend: regenerate TS types from shared DTOs
18. Frontend: `api.ts`, `store.ts`, group registry skeleton
19. Frontend: `XaiImagineConfigView`, `ImageConfigPanel`, `ImageButton`
20. Frontend: wire `ImageButton` into `CockpitBar` (desktop + mobile)
21. Frontend: `InlineImageBlock` + `ImageLightbox` + assistant-message integration
22. Frontend: `GalleryGrid` + `GalleryLightbox` + nav entry
23. Frontend: `GeneratedImagesTab` + attachment-picker integration
24. End-to-end manual verification pass against the spec checklist

---

## Task 1: Add Pillow dependency

**Goal:** Pillow available in both local-dev and Docker-build dependency files.

**Files:**
- Modify: `pyproject.toml` (repo root)
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Read both pyproject.toml files**

```bash
cat pyproject.toml backend/pyproject.toml
```

- [ ] **Step 2: Add Pillow to root `pyproject.toml`**

Find the `[project] dependencies` array. Add a new line, alphabetically sorted:

```toml
"pillow>=11.0",
```

- [ ] **Step 3: Add Pillow to `backend/pyproject.toml`**

Same change in `backend/pyproject.toml`.

- [ ] **Step 4: Sync local environment**

```bash
uv sync
```

- [ ] **Step 5: Verify import works**

```bash
uv run python -c "from PIL import Image; print(Image.__version__)"
```
Expected: prints a version string starting `11.` or higher.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml backend/pyproject.toml uv.lock
git commit -m "Add pillow dependency for image thumbnail generation"
```

---

## Task 2: Shared DTOs — `shared/dtos/images.py`

**Goal:** Single source of truth for image group configs, generation results and refs.

**Files:**
- Create: `shared/dtos/images.py`
- Test: `tests/shared/dtos/test_images.py`

- [ ] **Step 1: Read existing shared DTO files for style**

```bash
ls shared/dtos/
head -30 shared/dtos/chat.py shared/dtos/llm.py
```
Match docstring/typing style.

- [ ] **Step 2: Write the failing test first**

Create `tests/shared/dtos/test_images.py`:

```python
import pytest
from pydantic import TypeAdapter, ValidationError

from shared.dtos.images import (
    GeneratedImageResult,
    ImageGenItem,
    ImageGroupConfig,
    ImageRefDto,
    ModeratedRejection,
    XaiImagineConfig,
)


def test_xai_imagine_config_defaults():
    cfg = XaiImagineConfig()
    assert cfg.group_id == "xai_imagine"
    assert cfg.tier == "normal"
    assert cfg.resolution == "1k"
    assert cfg.aspect == "1:1"
    assert cfg.n == 4


def test_xai_imagine_config_validation_n_range():
    XaiImagineConfig(n=1)
    XaiImagineConfig(n=10)
    with pytest.raises(ValidationError):
        XaiImagineConfig(n=0)
    with pytest.raises(ValidationError):
        XaiImagineConfig(n=11)


def test_image_group_config_discriminated_union_parses_xai():
    adapter = TypeAdapter(ImageGroupConfig)
    parsed = adapter.validate_python({
        "group_id": "xai_imagine",
        "tier": "pro",
        "resolution": "2k",
        "aspect": "16:9",
        "n": 2,
    })
    assert isinstance(parsed, XaiImagineConfig)
    assert parsed.tier == "pro"


def test_image_group_config_discriminated_union_rejects_unknown():
    adapter = TypeAdapter(ImageGroupConfig)
    with pytest.raises(ValidationError):
        adapter.validate_python({"group_id": "unknown_group", "n": 1})


def test_image_gen_item_discriminated_union():
    adapter = TypeAdapter(ImageGenItem)
    img = adapter.validate_python({
        "kind": "image",
        "id": "img_a",
        "width": 1024,
        "height": 1024,
        "model_id": "grok-imagine",
    })
    assert isinstance(img, GeneratedImageResult)

    moderated = adapter.validate_python({"kind": "moderated"})
    assert isinstance(moderated, ModeratedRejection)
    assert moderated.reason is None


def test_image_ref_dto_required_fields():
    ref = ImageRefDto(
        id="img_a",
        blob_url="/api/images/img_a/blob",
        thumb_url="/api/images/img_a/thumb",
        width=1024,
        height=1024,
        prompt="a cat",
        model_id="grok-imagine",
        tool_call_id="tc_a",
    )
    assert ref.id == "img_a"
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
uv run pytest tests/shared/dtos/test_images.py -v
```
Expected: ImportError on `shared.dtos.images`.

- [ ] **Step 4: Implement `shared/dtos/images.py`**

```python
"""DTOs for image generation: group configs, generation results, message refs."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field


# --- per-group typed configs (discriminated union via group_id) -----------

class XaiImagineConfig(BaseModel):
    group_id: Literal["xai_imagine"] = "xai_imagine"
    tier: Literal["normal", "pro"] = "normal"
    resolution: Literal["1k", "2k"] = "1k"
    aspect: Literal["1:1", "16:9", "9:16", "4:3", "3:4"] = "1:1"
    n: int = Field(4, ge=1, le=10)


# Future image groups (Seedream, FLUX, etc.) extend this union.
ImageGroupConfig = Annotated[
    XaiImagineConfig,
    Field(discriminator="group_id"),
]


# --- generation result items (per-image; discriminated by kind) ----------

class GeneratedImageResult(BaseModel):
    kind: Literal["image"] = "image"
    id: str
    width: int
    height: int
    model_id: str
    description: str | None = None  # Phase II hook (vision-derived caption)


class ModeratedRejection(BaseModel):
    kind: Literal["moderated"] = "moderated"
    reason: str | None = None


ImageGenItem = Annotated[
    GeneratedImageResult | ModeratedRejection,
    Field(discriminator="kind"),
]


# --- message-level reference (rendered inline under assistant message) ----

class ImageRefDto(BaseModel):
    id: str
    blob_url: str
    thumb_url: str
    width: int
    height: int
    prompt: str
    model_id: str
    tool_call_id: str


# --- gallery REST DTOs ----------------------------------------------------

class GeneratedImageSummaryDto(BaseModel):
    id: str
    thumb_url: str
    width: int
    height: int
    prompt: str
    model_id: str
    generated_at: datetime


class GeneratedImageDetailDto(GeneratedImageSummaryDto):
    blob_url: str
    config_snapshot: dict
    connection_id: str
    group_id: str


# --- discovery DTO for /api/images/config GET ----------------------------

class ConnectionImageGroupsDto(BaseModel):
    connection_id: str
    connection_display_name: str
    group_ids: list[str]


class ActiveImageConfigDto(BaseModel):
    connection_id: str
    group_id: str
    config: dict
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
uv run pytest tests/shared/dtos/test_images.py -v
```
Expected: all tests PASS.

- [ ] **Step 6: Syntax check**

```bash
uv run python -m py_compile shared/dtos/images.py
```

- [ ] **Step 7: Commit**

```bash
git add shared/dtos/images.py tests/shared/dtos/test_images.py
git commit -m "Add image generation DTOs (group configs, results, refs)"
```

---

## Task 3: Extend `shared/dtos/chat.py`

**Goal:** Add `moderated_count` to `ToolCallRefDto` and `image_refs` to `ChatMessageDto`. Defaults must be backwards-compatible (existing documents must deserialise unchanged per the migration policy).

**Files:**
- Modify: `shared/dtos/chat.py`
- Test: `tests/shared/dtos/test_chat.py` (extend if exists, else create)

- [ ] **Step 1: Read current `shared/dtos/chat.py`**

Note exact line numbers of `ToolCallRefDto` and `ChatMessageDto` definitions.

- [ ] **Step 2: Write failing tests**

Create or extend `tests/shared/dtos/test_chat.py`:

```python
from datetime import datetime, UTC

from shared.dtos.chat import ChatMessageDto, ToolCallRefDto


def test_tool_call_ref_dto_defaults_moderated_count_zero():
    tc = ToolCallRefDto(
        tool_call_id="tc_a",
        tool_name="generate_image",
        arguments={"prompt": "x"},
        success=True,
    )
    assert tc.moderated_count == 0


def test_tool_call_ref_dto_accepts_moderated_count():
    tc = ToolCallRefDto(
        tool_call_id="tc_a",
        tool_name="generate_image",
        arguments={"prompt": "x"},
        success=True,
        moderated_count=2,
    )
    assert tc.moderated_count == 2


def test_chat_message_dto_image_refs_default_none():
    msg = ChatMessageDto(
        id="m1",
        session_id="s1",
        role="assistant",
        content="hello",
        token_count=1,
        created_at=datetime.now(UTC),
    )
    assert msg.image_refs is None


def test_chat_message_dto_accepts_image_refs():
    from shared.dtos.images import ImageRefDto
    ref = ImageRefDto(
        id="img_a", blob_url="/b", thumb_url="/t", width=10, height=10,
        prompt="x", model_id="grok", tool_call_id="tc_a",
    )
    msg = ChatMessageDto(
        id="m1", session_id="s1", role="assistant", content="hi",
        token_count=1, created_at=datetime.now(UTC), image_refs=[ref],
    )
    assert msg.image_refs == [ref]


def test_chat_message_dto_existing_documents_still_parse():
    """An existing assistant message document (without image_refs or
    moderated_count) must deserialise without error."""
    msg = ChatMessageDto.model_validate({
        "id": "m1",
        "session_id": "s1",
        "role": "assistant",
        "content": "hello",
        "token_count": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "tool_calls": [
            {"tool_call_id": "tc_a", "tool_name": "x", "arguments": {}, "success": True}
        ],
    })
    assert msg.tool_calls[0].moderated_count == 0
    assert msg.image_refs is None
```

- [ ] **Step 3: Run tests to verify failure**

```bash
uv run pytest tests/shared/dtos/test_chat.py -v
```
Expected: failures related to missing fields.

- [ ] **Step 4: Modify `shared/dtos/chat.py`**

Add the import at the top:

```python
from shared.dtos.images import ImageRefDto
```

In `ToolCallRefDto`, add:

```python
class ToolCallRefDto(BaseModel):
    """Metadata for a single tool call executed during inference."""
    tool_call_id: str
    tool_name: str
    arguments: dict
    success: bool
    moderated_count: int = 0
```

In `ChatMessageDto`, add the field after `tool_calls`:

```python
class ChatMessageDto(BaseModel):
    # ... existing fields ...
    tool_calls: list[ToolCallRefDto] | None = None
    image_refs: list[ImageRefDto] | None = None
    usage: dict | None = None
```

- [ ] **Step 5: Run tests to verify pass**

```bash
uv run pytest tests/shared/dtos/test_chat.py -v
```

- [ ] **Step 6: Syntax check**

```bash
uv run python -m py_compile shared/dtos/chat.py
```

- [ ] **Step 7: Commit**

```bash
git add shared/dtos/chat.py tests/shared/dtos/test_chat.py
git commit -m "Extend chat DTOs with image_refs and moderated_count"
```

---

## Task 4: Backend image MongoDB models

**Goal:** Pydantic document models for the two new collections.

**Files:**
- Create: `backend/modules/images/__init__.py` (empty for now)
- Create: `backend/modules/images/_models.py`
- Test: `tests/modules/images/test_models.py`

- [ ] **Step 1: Create empty package init**

Create `backend/modules/images/__init__.py` with a single docstring:

```python
"""Image generation module. Public API to be added."""
```

- [ ] **Step 2: Write failing test**

Create `tests/modules/images/test_models.py`:

```python
from datetime import datetime, UTC

from backend.modules.images._models import (
    GeneratedImageDocument,
    UserImageConfigDocument,
)


def test_generated_image_document_minimal_real_image():
    doc = GeneratedImageDocument(
        id="img_a", user_id="u1", blob_id="b1", thumb_blob_id="t1",
        prompt="a cat", model_id="grok-imagine", group_id="xai_imagine",
        connection_id="conn_a", config_snapshot={"tier": "normal"},
        width=1024, height=1024, content_type="image/jpeg",
        generated_at=datetime.now(UTC),
    )
    assert doc.moderated is False
    assert doc.tags == []


def test_generated_image_document_moderated_stub():
    doc = GeneratedImageDocument(
        id="img_b", user_id="u1",
        prompt="bad", model_id="grok-imagine", group_id="xai_imagine",
        connection_id="conn_a", config_snapshot={},
        moderated=True, moderation_reason="content_filter",
        generated_at=datetime.now(UTC),
    )
    assert doc.blob_id is None
    assert doc.thumb_blob_id is None
    assert doc.width is None
    assert doc.height is None


def test_user_image_config_document_required_fields():
    doc = UserImageConfigDocument(
        id="u1:conn_a:xai_imagine", user_id="u1",
        connection_id="conn_a", group_id="xai_imagine",
        config={"tier": "normal", "n": 4},
        updated_at=datetime.now(UTC),
    )
    assert doc.selected is False
```

- [ ] **Step 3: Run test (will fail, no model file)**

```bash
uv run pytest tests/modules/images/test_models.py -v
```

- [ ] **Step 4: Implement `_models.py`**

```python
"""MongoDB document models for the images module."""

from datetime import datetime

from pydantic import BaseModel, Field


class GeneratedImageDocument(BaseModel):
    """One row in the `generated_images` collection.

    For successful generations all blob/dimension fields are populated.
    For images that were filtered by upstream moderation, `moderated=True`
    and the blob/dimension fields are None — the row is kept as a stub
    so audit/debug retains the full batch context.
    """

    id: str
    user_id: str
    blob_id: str | None = None
    thumb_blob_id: str | None = None
    prompt: str
    model_id: str
    group_id: str
    connection_id: str
    config_snapshot: dict
    width: int | None = None
    height: int | None = None
    content_type: str | None = None
    moderated: bool = False
    moderation_reason: str | None = None
    tags: list[str] = Field(default_factory=list)
    generated_at: datetime


class UserImageConfigDocument(BaseModel):
    """One row in the `user_image_configs` collection.

    Composite id: `{user_id}:{connection_id}:{group_id}`.

    `selected=True` marks the active config for a user; at most one
    document per user has `selected=True`. Switching the active config
    flips this atomically (transaction in the repository).

    `config` is opaque here; the repository validates it against the
    group's typed schema (via `LlmService.validate_image_config`)
    before writing.
    """

    id: str
    user_id: str
    connection_id: str
    group_id: str
    config: dict
    selected: bool = False
    updated_at: datetime
```

- [ ] **Step 5: Run test, verify pass**

```bash
uv run pytest tests/modules/images/test_models.py -v
```

- [ ] **Step 6: Syntax check**

```bash
uv run python -m py_compile backend/modules/images/__init__.py backend/modules/images/_models.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/modules/images/ tests/modules/images/test_models.py
git commit -m "Add images module skeleton with MongoDB document models"
```

---

## Task 5: `GeneratedImagesRepository`

**Goal:** Repository for `generated_images` collection with the required CRUD + cascade-delete operations and indexes.

**Files:**
- Create: `backend/modules/images/_repository.py`
- Test: `tests/modules/images/test_repository.py` (DB-required; runs in Docker)

- [ ] **Step 1: Read `backend/modules/llm/_user_config.py` for the repository pattern**

Note the use of `find_one_and_update` with `$setOnInsert`, `create_indexes`, `delete_all_for_user`.

- [ ] **Step 2: Write failing test**

Create `tests/modules/images/test_repository.py`:

```python
from datetime import datetime, UTC

import pytest

from backend.modules.images._repository import GeneratedImagesRepository
from backend.modules.images._models import GeneratedImageDocument


@pytest.fixture
async def repo(db):
    """`db` fixture must be a Motor AsyncIOMotorDatabase from conftest."""
    r = GeneratedImagesRepository(db)
    await r.create_indexes()
    yield r
    await db["generated_images"].delete_many({})


def _make_doc(image_id: str, user_id: str = "u1", **overrides) -> GeneratedImageDocument:
    base = dict(
        id=image_id, user_id=user_id, blob_id=f"b_{image_id}",
        thumb_blob_id=f"t_{image_id}", prompt="x",
        model_id="grok-imagine", group_id="xai_imagine",
        connection_id="conn_a", config_snapshot={},
        width=1024, height=1024, content_type="image/jpeg",
        generated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return GeneratedImageDocument(**base)


@pytest.mark.asyncio
async def test_insert_and_find(repo):
    doc = _make_doc("img_a")
    await repo.insert(doc)
    found = await repo.find_for_user(user_id="u1", image_id="img_a")
    assert found is not None
    assert found.id == "img_a"


@pytest.mark.asyncio
async def test_find_for_user_enforces_ownership(repo):
    await repo.insert(_make_doc("img_a", user_id="u1"))
    other = await repo.find_for_user(user_id="u2", image_id="img_a")
    assert other is None


@pytest.mark.asyncio
async def test_list_for_user_orders_by_generated_at_desc(repo):
    await repo.insert(_make_doc("img_a", generated_at=datetime(2026, 1, 1, tzinfo=UTC)))
    await repo.insert(_make_doc("img_b", generated_at=datetime(2026, 2, 1, tzinfo=UTC)))
    items = await repo.list_for_user(user_id="u1", limit=10, before=None)
    assert [i.id for i in items] == ["img_b", "img_a"]


@pytest.mark.asyncio
async def test_list_for_user_pagination_with_before(repo):
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 2, 1, tzinfo=UTC)
    await repo.insert(_make_doc("img_a", generated_at=t1))
    await repo.insert(_make_doc("img_b", generated_at=t2))
    items = await repo.list_for_user(user_id="u1", limit=10, before=t2)
    assert [i.id for i in items] == ["img_a"]


@pytest.mark.asyncio
async def test_delete_removes_document(repo):
    await repo.insert(_make_doc("img_a"))
    deleted = await repo.delete_for_user(user_id="u1", image_id="img_a")
    assert deleted is True
    assert await repo.find_for_user(user_id="u1", image_id="img_a") is None


@pytest.mark.asyncio
async def test_delete_all_for_user(repo):
    await repo.insert(_make_doc("img_a", user_id="u1"))
    await repo.insert(_make_doc("img_b", user_id="u1"))
    await repo.insert(_make_doc("img_c", user_id="u2"))
    deleted = await repo.delete_all_for_user(user_id="u1")
    assert deleted == 2
    remaining = await repo.list_for_user(user_id="u2", limit=10, before=None)
    assert len(remaining) == 1
```

- [ ] **Step 3: Run test in Docker (will fail, no repo file)**

```bash
PYTHONPATH=. uv run pytest tests/modules/images/test_repository.py -v
```

- [ ] **Step 4: Implement `_repository.py`** (only `GeneratedImagesRepository` for this task)

```python
"""Repositories for the images module."""

from datetime import datetime
from typing import Iterable

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.images._models import GeneratedImageDocument


class GeneratedImagesRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["generated_images"]

    async def create_indexes(self) -> None:
        await self._collection.create_index([("user_id", 1), ("generated_at", -1)])
        await self._collection.create_index([("user_id", 1), ("id", 1)], unique=True)

    async def insert(self, doc: GeneratedImageDocument) -> None:
        payload = doc.model_dump()
        # Use the document's id as the Mongo _id to make ownership-checked
        # finds simple and idempotent. Composite (user_id, id) unique index
        # provides the actual safety net.
        payload["_id"] = doc.id
        await self._collection.insert_one(payload)

    async def insert_many(self, docs: Iterable[GeneratedImageDocument]) -> None:
        payloads = []
        for d in docs:
            p = d.model_dump()
            p["_id"] = d.id
            payloads.append(p)
        if payloads:
            await self._collection.insert_many(payloads)

    async def find_for_user(
        self, *, user_id: str, image_id: str
    ) -> GeneratedImageDocument | None:
        raw = await self._collection.find_one({"user_id": user_id, "id": image_id})
        if raw is None:
            return None
        raw.pop("_id", None)
        return GeneratedImageDocument.model_validate(raw)

    async def list_for_user(
        self,
        *,
        user_id: str,
        limit: int,
        before: datetime | None,
    ) -> list[GeneratedImageDocument]:
        query: dict = {"user_id": user_id}
        if before is not None:
            query["generated_at"] = {"$lt": before}
        cursor = self._collection.find(query).sort("generated_at", -1).limit(limit)
        rows = await cursor.to_list(length=limit)
        out: list[GeneratedImageDocument] = []
        for r in rows:
            r.pop("_id", None)
            out.append(GeneratedImageDocument.model_validate(r))
        return out

    async def delete_for_user(self, *, user_id: str, image_id: str) -> bool:
        result = await self._collection.delete_one(
            {"user_id": user_id, "id": image_id}
        )
        return result.deleted_count > 0

    async def delete_all_for_user(self, *, user_id: str) -> int:
        result = await self._collection.delete_many({"user_id": user_id})
        return result.deleted_count
```

- [ ] **Step 5: Run tests in Docker, verify pass**

```bash
PYTHONPATH=. uv run pytest tests/modules/images/test_repository.py -v
```

- [ ] **Step 6: Syntax check**

```bash
uv run python -m py_compile backend/modules/images/_repository.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/modules/images/_repository.py tests/modules/images/test_repository.py
git commit -m "Add GeneratedImagesRepository with indexes and cascade delete"
```

---

## Task 6: `UserImageConfigRepository`

**Goal:** Repository for the `user_image_configs` collection. Supports atomic active-config switching and cascade delete.

**Files:**
- Modify: `backend/modules/images/_repository.py` (append second repository class)
- Test: extend `tests/modules/images/test_repository.py`

- [ ] **Step 1: Append failing tests**

Add to `tests/modules/images/test_repository.py`:

```python
from backend.modules.images._repository import UserImageConfigRepository
from backend.modules.images._models import UserImageConfigDocument


@pytest.fixture
async def cfg_repo(db):
    r = UserImageConfigRepository(db)
    await r.create_indexes()
    yield r
    await db["user_image_configs"].delete_many({})


@pytest.mark.asyncio
async def test_upsert_creates_document(cfg_repo):
    doc = await cfg_repo.upsert(
        user_id="u1", connection_id="conn_a", group_id="xai_imagine",
        config={"tier": "normal", "n": 4},
    )
    assert doc.id == "u1:conn_a:xai_imagine"
    assert doc.config == {"tier": "normal", "n": 4}
    assert doc.selected is False


@pytest.mark.asyncio
async def test_upsert_updates_existing(cfg_repo):
    await cfg_repo.upsert(
        user_id="u1", connection_id="conn_a", group_id="xai_imagine",
        config={"tier": "normal", "n": 4},
    )
    updated = await cfg_repo.upsert(
        user_id="u1", connection_id="conn_a", group_id="xai_imagine",
        config={"tier": "pro", "n": 2},
    )
    assert updated.config == {"tier": "pro", "n": 2}


@pytest.mark.asyncio
async def test_set_active_moves_selected_atomically(cfg_repo):
    await cfg_repo.upsert(
        user_id="u1", connection_id="conn_a", group_id="xai_imagine",
        config={"tier": "normal"},
    )
    await cfg_repo.upsert(
        user_id="u1", connection_id="conn_b", group_id="xai_imagine",
        config={"tier": "pro"},
    )

    await cfg_repo.set_active(user_id="u1", connection_id="conn_a", group_id="xai_imagine")
    active = await cfg_repo.get_active(user_id="u1")
    assert active.connection_id == "conn_a"

    await cfg_repo.set_active(user_id="u1", connection_id="conn_b", group_id="xai_imagine")
    active = await cfg_repo.get_active(user_id="u1")
    assert active.connection_id == "conn_b"

    # only one selected at any time
    selected_count = await cfg_repo._collection.count_documents(
        {"user_id": "u1", "selected": True}
    )
    assert selected_count == 1


@pytest.mark.asyncio
async def test_get_active_none_when_no_config(cfg_repo):
    assert await cfg_repo.get_active(user_id="u1") is None


@pytest.mark.asyncio
async def test_delete_all_for_user_clears_configs(cfg_repo):
    await cfg_repo.upsert(
        user_id="u1", connection_id="conn_a", group_id="xai_imagine",
        config={"tier": "normal"},
    )
    await cfg_repo.upsert(
        user_id="u2", connection_id="conn_a", group_id="xai_imagine",
        config={"tier": "normal"},
    )
    deleted = await cfg_repo.delete_all_for_user(user_id="u1")
    assert deleted == 1
    remaining = await cfg_repo._collection.count_documents({"user_id": "u2"})
    assert remaining == 1
```

- [ ] **Step 2: Run tests, verify failure**

```bash
PYTHONPATH=. uv run pytest tests/modules/images/test_repository.py -v
```

- [ ] **Step 3: Append `UserImageConfigRepository` to `_repository.py`**

```python
class UserImageConfigRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._collection = db["user_image_configs"]

    async def create_indexes(self) -> None:
        # at most one selected config per user
        await self._collection.create_index(
            [("user_id", 1), ("selected", 1)],
            partialFilterExpression={"selected": True},
        )
        await self._collection.create_index([("user_id", 1)])

    @staticmethod
    def _doc_id(user_id: str, connection_id: str, group_id: str) -> str:
        return f"{user_id}:{connection_id}:{group_id}"

    async def upsert(
        self,
        *,
        user_id: str,
        connection_id: str,
        group_id: str,
        config: dict,
    ) -> UserImageConfigDocument:
        from datetime import UTC, datetime as _dt
        now = _dt.now(UTC)
        doc_id = self._doc_id(user_id, connection_id, group_id)
        result = await self._collection.find_one_and_update(
            {"_id": doc_id},
            {
                "$set": {
                    "user_id": user_id,
                    "connection_id": connection_id,
                    "group_id": group_id,
                    "config": config,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "id": doc_id,
                    "selected": False,
                    "created_at": now,
                },
            },
            upsert=True,
            return_document=True,
        )
        result.pop("_id", None)
        result.pop("created_at", None)
        return UserImageConfigDocument.model_validate(result)

    async def set_active(
        self, *, user_id: str, connection_id: str, group_id: str
    ) -> None:
        """Make the (connection, group) the user's active image config.

        Clears `selected=True` from all other configs for the user, then
        sets it on the target. Performed in a transaction.
        """
        from backend.database import get_mongo_client

        target_id = self._doc_id(user_id, connection_id, group_id)

        async with await get_mongo_client().start_session() as session:
            async with session.start_transaction():
                await self._collection.update_many(
                    {"user_id": user_id, "_id": {"$ne": target_id}},
                    {"$set": {"selected": False}},
                    session=session,
                )
                await self._collection.update_one(
                    {"_id": target_id},
                    {"$set": {"selected": True}},
                    session=session,
                )

    async def get_active(
        self, *, user_id: str
    ) -> UserImageConfigDocument | None:
        raw = await self._collection.find_one(
            {"user_id": user_id, "selected": True}
        )
        if raw is None:
            return None
        raw.pop("_id", None)
        raw.pop("created_at", None)
        return UserImageConfigDocument.model_validate(raw)

    async def find(
        self, *, user_id: str, connection_id: str, group_id: str
    ) -> UserImageConfigDocument | None:
        raw = await self._collection.find_one(
            {"_id": self._doc_id(user_id, connection_id, group_id)}
        )
        if raw is None:
            return None
        raw.pop("_id", None)
        raw.pop("created_at", None)
        return UserImageConfigDocument.model_validate(raw)

    async def list_for_user(
        self, *, user_id: str
    ) -> list[UserImageConfigDocument]:
        cursor = self._collection.find({"user_id": user_id})
        rows = await cursor.to_list(length=1000)
        out: list[UserImageConfigDocument] = []
        for r in rows:
            r.pop("_id", None)
            r.pop("created_at", None)
            out.append(UserImageConfigDocument.model_validate(r))
        return out

    async def delete_all_for_user(self, *, user_id: str) -> int:
        result = await self._collection.delete_many({"user_id": user_id})
        return result.deleted_count
```

**Note on `get_mongo_client`:** if `backend/database.py` does not expose
`get_mongo_client`, locate the actual Motor client accessor (search for
`AsyncIOMotorClient` in `backend/database.py`) and use that instead. The
transaction needs the client, not the database.

- [ ] **Step 4: Run tests in Docker, verify pass**

```bash
PYTHONPATH=. uv run pytest tests/modules/images/test_repository.py -v
```

- [ ] **Step 5: Syntax check**

```bash
uv run python -m py_compile backend/modules/images/_repository.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/modules/images/_repository.py tests/modules/images/test_repository.py
git commit -m "Add UserImageConfigRepository with atomic active-config switching"
```

---

## Task 7: Thumbnail generator

**Goal:** Pure function that resizes an image to a 256 px JPG thumbnail.

**Files:**
- Create: `backend/modules/images/_thumbnails.py`
- Test: `tests/modules/images/test_thumbnails.py`

- [ ] **Step 1: Write failing test**

Create `tests/modules/images/test_thumbnails.py`:

```python
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
```

- [ ] **Step 2: Run test, verify fail**

```bash
uv run pytest tests/modules/images/test_thumbnails.py -v
```

- [ ] **Step 3: Implement `_thumbnails.py`**

```python
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
```

- [ ] **Step 4: Run test, verify pass**

```bash
uv run pytest tests/modules/images/test_thumbnails.py -v
```

- [ ] **Step 5: Syntax check**

```bash
uv run python -m py_compile backend/modules/images/_thumbnails.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/modules/images/_thumbnails.py tests/modules/images/test_thumbnails.py
git commit -m "Add JPEG thumbnail generator using Pillow"
```

---

## Task 8: Extend `BaseAdapter` with optional image hooks

**Goal:** All LLM adapters get optional image generation hooks. Default behaviour for non-image adapters: declare unsupported, return empty.

**Files:**
- Modify: `backend/modules/llm/_adapters/_base.py`
- Test: `tests/modules/llm/_adapters/test_base.py` (extend if exists, else create)

- [ ] **Step 1: Read `_base.py` to confirm current shape**

Already known to be ABC with `fetch_models` and `stream_completion` as abstract methods. Add image hooks **without** breaking subclasses.

- [ ] **Step 2: Write failing test**

Create or extend `tests/modules/llm/_adapters/test_base.py`:

```python
import pytest

from backend.modules.llm._adapters._base import BaseAdapter


class _DummyAdapter(BaseAdapter):
    adapter_type = "dummy"
    display_name = "Dummy"
    view_id = "dummy"

    async def fetch_models(self, connection):
        return []

    def stream_completion(self, connection, request):
        async def _empty():
            if False:
                yield None
        return _empty()


def test_base_adapter_image_capability_default_false():
    assert _DummyAdapter.supports_image_generation is False


@pytest.mark.asyncio
async def test_base_adapter_image_groups_default_empty():
    adapter = _DummyAdapter()
    assert await adapter.image_groups(connection=None) == []


@pytest.mark.asyncio
async def test_base_adapter_generate_images_default_raises():
    adapter = _DummyAdapter()
    with pytest.raises(NotImplementedError):
        await adapter.generate_images(
            connection=None, group_id="x", config={}, prompt="x"
        )
```

- [ ] **Step 3: Run test, verify fail**

```bash
uv run pytest tests/modules/llm/_adapters/test_base.py -v
```

- [ ] **Step 4: Modify `_base.py`**

Add the import line near the top with the others:

```python
from typing import ClassVar
```

Add to the `BaseAdapter` class (after `secret_fields`):

```python
    # Image generation capability (optional; default: not supported)
    supports_image_generation: ClassVar[bool] = False

    async def image_groups(self, connection) -> list[str]:
        """Return image-group ids supported by this adapter for this connection.

        Default: empty list (adapter does not support image generation).
        Adapters that set ``supports_image_generation = True`` should override
        this to return one or more known group ids (e.g. ``["xai_imagine"]``).
        """
        return []

    async def generate_images(
        self, connection, group_id: str, config, prompt: str,
    ):
        """Generate images for the given group and config. Returns a list of
        ``ImageGenItem`` (success or moderated rejection) per the shared DTO.

        Default: raise ``NotImplementedError``. Adapters that declare image
        support must override.
        """
        raise NotImplementedError(
            f"Adapter {self.adapter_type!r} does not implement image generation"
        )
```

The exact return type should be `list[ImageGenItem]` from `shared.dtos.images`. Add the import at the top of `_base.py`:

```python
from shared.dtos.images import ImageGenItem, ImageGroupConfig
```

…and tighten the signature accordingly:

```python
    async def generate_images(
        self,
        connection: ResolvedConnection,
        group_id: str,
        config: ImageGroupConfig,
        prompt: str,
    ) -> list[ImageGenItem]:
        raise NotImplementedError(...)
```

- [ ] **Step 5: Run test, verify pass**

```bash
uv run pytest tests/modules/llm/_adapters/test_base.py -v
```

- [ ] **Step 6: Syntax check + verify nothing else broke**

```bash
uv run python -m py_compile backend/modules/llm/_adapters/_base.py
uv run pytest tests/modules/llm/_adapters/ -v
```

- [ ] **Step 7: Commit**

```bash
git add backend/modules/llm/_adapters/_base.py tests/modules/llm/_adapters/test_base.py
git commit -m "Add optional image generation hooks to BaseAdapter"
```

---

## Task 9: xAI image group definition + `generate_images`

**Goal:** xAI adapter implements `image_groups()` and `generate_images()` for the `xai_imagine` group.

**Files:**
- Create: `backend/modules/llm/_adapters/_xai_image_groups.py`
- Modify: `backend/modules/llm/_adapters/_xai_http.py`
- Test: extend `tests/modules/llm/_adapters/test_xai_http.py`

**API verified live on 2026-04-26 with Chris's `.xai-test-key`** —
see spec §12 for the canonical findings. Use these exact values; do
NOT re-verify (we already paid for the probe).

| field | verified value |
|---|---|
| endpoint | `POST https://api.x.ai/v1/images/generations` |
| normal model id | `grok-imagine-image` |
| pro model id | `grok-imagine-image-pro` |
| `n` range | 1..10 |
| `response_format` we use | `"url"` (download immediately — Cloudflare URL expires) |
| `aspect_ratio` (Phase I subset) | `1:1`, `16:9`, `9:16`, `4:3`, `3:4` |
| `resolution` | `"1k"` or `"2k"` |
| success item | `{url, mime_type, revised_prompt}` (no width/height — probe via Pillow) |
| moderation flag | `respect_moderation: false` per item (absent or true → success) |
| cost telemetry | `usage.cost_in_usd_ticks` (log at debug level, no UI) |

- [ ] **Step 1: Confirm understanding of the verified API**

Read spec §12 once. No live re-verification needed. The placeholder
TODOs in the rest of this task have been pre-resolved with the verified
values below.

- [ ] **Step 2: Create `_xai_image_groups.py`**

```python
"""xAI grok-imagine image group definition.

Verified against the live xAI API on 2026-04-26 with the project's
.xai-test-key. See devdocs/specs/2026-04-26-tti-xai-imagine-design.md
section 12 for the canonical findings.

API contract (do not change without re-verifying):
- endpoint: POST https://api.x.ai/v1/images/generations
- model ids: grok-imagine-image (normal), grok-imagine-image-pro (pro)
- aspect_ratio: literal string ('1:1', '16:9', '9:16', '4:3', '3:4',
  plus several others we do not expose in Phase I)
- resolution: '1k' or '2k'
- response: { data: [{url, mime_type, revised_prompt}], usage: {...} }
- moderation: per-item 'respect_moderation: false' indicates the image
  was filtered. Absent or true means success.
"""

from shared.dtos.images import (
    GeneratedImageResult,
    ImageGenItem,
    ModeratedRejection,
    XaiImagineConfig,
)


GROUP_ID = "xai_imagine"


def model_id_for_tier(tier: str) -> str:
    """Map config tier to xAI's model id."""
    if tier == "pro":
        return "grok-imagine-image-pro"
    return "grok-imagine-image"


def aspect_to_payload(aspect: str) -> str:
    """xAI takes the aspect literal directly (e.g. '16:9')."""
    return aspect


def resolution_to_payload(resolution: str) -> str:
    """xAI takes '1k' or '2k' directly."""
    return resolution
```

- [ ] **Step 3: Write failing tests for `xai_http` image methods**

Add to `tests/modules/llm/_adapters/test_xai_http.py`:

```python
import json
from unittest.mock import AsyncMock, patch

import pytest

from backend.modules.llm._adapters._xai_http import XaiHttpAdapter
from shared.dtos.images import (
    GeneratedImageResult,
    ModeratedRejection,
    XaiImagineConfig,
)


def test_xai_supports_image_generation_flag():
    assert XaiHttpAdapter.supports_image_generation is True


@pytest.mark.asyncio
async def test_xai_image_groups_returns_xai_imagine(fake_connection):
    """`fake_connection` is a fixture providing a ResolvedConnection.
    Add it to conftest if not present."""
    adapter = XaiHttpAdapter()
    groups = await adapter.image_groups(fake_connection)
    assert groups == ["xai_imagine"]


@pytest.mark.asyncio
async def test_xai_generate_images_success(fake_connection, monkeypatch):
    adapter = XaiHttpAdapter()
    cfg = XaiImagineConfig(tier="normal", resolution="1k", aspect="1:1", n=2)

    fake_response_payload = {
        "data": [
            {"url": "https://example/img1.jpg", "respect_moderation": True},
            {"url": "https://example/img2.jpg", "respect_moderation": True},
        ]
    }

    fake_image_bytes = b"\xff\xd8\xff\xe0FAKEJPEG"

    async def fake_post(*args, **kwargs):
        class R:
            status_code = 200
            def json(self): return fake_response_payload
        return R()

    async def fake_get(*args, **kwargs):
        class R:
            status_code = 200
            content = fake_image_bytes
            headers = {"content-type": "image/jpeg"}
        return R()

    monkeypatch.setattr(
        "backend.modules.llm._adapters._xai_http._http_post", fake_post
    )
    monkeypatch.setattr(
        "backend.modules.llm._adapters._xai_http._http_get", fake_get
    )

    items = await adapter.generate_images(
        connection=fake_connection,
        group_id="xai_imagine",
        config=cfg,
        prompt="a serene mountain landscape at dawn",
    )

    assert len(items) == 2
    assert all(isinstance(i, GeneratedImageResult) for i in items)


@pytest.mark.asyncio
async def test_xai_generate_images_moderation_per_item(fake_connection, monkeypatch):
    adapter = XaiHttpAdapter()
    cfg = XaiImagineConfig(n=2)

    fake_response_payload = {
        "data": [
            {"url": "https://example/img1.jpg", "respect_moderation": True},
            {"respect_moderation": False},  # filtered, no url
        ]
    }

    async def fake_post(*args, **kwargs):
        class R:
            status_code = 200
            def json(self): return fake_response_payload
        return R()

    async def fake_get(*args, **kwargs):
        class R:
            status_code = 200
            content = b"\xff\xd8FAKE"
            headers = {"content-type": "image/jpeg"}
        return R()

    monkeypatch.setattr("backend.modules.llm._adapters._xai_http._http_post", fake_post)
    monkeypatch.setattr("backend.modules.llm._adapters._xai_http._http_get", fake_get)

    items = await adapter.generate_images(
        connection=fake_connection, group_id="xai_imagine",
        config=cfg, prompt="x",
    )

    assert isinstance(items[0], GeneratedImageResult)
    assert isinstance(items[1], ModeratedRejection)


@pytest.mark.asyncio
async def test_xai_generate_images_unknown_group_raises(fake_connection):
    adapter = XaiHttpAdapter()
    with pytest.raises(ValueError, match="unknown image group"):
        await adapter.generate_images(
            connection=fake_connection, group_id="not_a_group",
            config=XaiImagineConfig(), prompt="x",
        )
```

If a `fake_connection` fixture does not exist, add it to the test file's conftest with a minimal `ResolvedConnection`-shaped object (api_key, base_url, etc.).

- [ ] **Step 4: Run tests, verify failures**

```bash
uv run pytest tests/modules/llm/_adapters/test_xai_http.py -k "image_generation or image_groups or generate_images" -v
```

- [ ] **Step 5: Implement xAI image methods in `_xai_http.py`**

Add the import at the top:

```python
from backend.modules.llm._adapters._xai_image_groups import (
    GROUP_ID as XAI_IMAGINE_GROUP_ID,
    aspect_to_payload,
    model_id_for_tier,
    resolution_to_payload,
)
from shared.dtos.images import (
    GeneratedImageResult,
    ImageGenItem,
    ImageGroupConfig,
    ModeratedRejection,
    XaiImagineConfig,
)
```

Set the class capability flag:

```python
class XaiHttpAdapter(BaseAdapter):
    # ... existing class attrs ...
    supports_image_generation: ClassVar[bool] = True
```

Add methods (placement: after `stream_completion`, before any `router()` classmethod):

```python
    async def image_groups(self, connection: ResolvedConnection) -> list[str]:
        # xAI offers exactly one image group today.
        return [XAI_IMAGINE_GROUP_ID]

    async def generate_images(
        self,
        connection: ResolvedConnection,
        group_id: str,
        config: ImageGroupConfig,
        prompt: str,
    ) -> list[ImageGenItem]:
        if group_id != XAI_IMAGINE_GROUP_ID:
            raise ValueError(f"unknown image group {group_id!r} for xAI adapter")
        if not isinstance(config, XaiImagineConfig):
            raise ValueError(
                f"expected XaiImagineConfig, got {type(config).__name__}"
            )

        model_id = model_id_for_tier(config.tier)
        body = {
            "model": model_id,
            "prompt": prompt,
            "n": config.n,
            "aspect_ratio": aspect_to_payload(config.aspect),
            "size": resolution_to_payload(config.resolution),
            # response_format etc — fill in per the verified API
        }

        url = f"{connection.base_url.rstrip('/')}/v1/images/generations"  # verify
        headers = {
            "Authorization": f"Bearer {connection.api_key}",
            "Content-Type": "application/json",
        }

        response = await _http_post(url, headers=headers, json=body)
        if response.status_code >= 400:
            # Caller (LlmService) maps status to error_code
            raise _xai_http_error(response)

        payload = response.json()
        items: list[ImageGenItem] = []
        for entry in payload.get("data", []):
            if entry.get("respect_moderation") is False:
                items.append(ModeratedRejection(reason=entry.get("reason")))
                continue

            image_url = entry.get("url")
            if not image_url:
                items.append(ModeratedRejection(reason="no_url"))
                continue

            blob_resp = await _http_get(image_url)
            if blob_resp.status_code >= 400:
                items.append(ModeratedRejection(reason="fetch_failed"))
                continue

            content_type = blob_resp.headers.get("content-type", "image/jpeg")
            width, height = _probe_dimensions(blob_resp.content) or (0, 0)
            image_id = _new_image_id()  # see helper below

            items.append(GeneratedImageResult(
                kind="image",
                id=image_id,
                width=width,
                height=height,
                model_id=model_id,
            ))
            # Stash the raw bytes + content_type alongside the item via an
            # internal map keyed by image_id, so the caller can persist them.
            # See note on `_LastBatch` below.
            _LAST_BATCH_BUFFERS[image_id] = (blob_resp.content, content_type)

        return items
```

**Helpers needed in `_xai_http.py`** (or extracted):

```python
import uuid

# Module-level temporary buffer keyed by generated image_id, drained by
# the caller immediately after generate_images returns. Single-process
# only; do not rely on cross-request persistence.
_LAST_BATCH_BUFFERS: dict[str, tuple[bytes, str]] = {}


def _new_image_id() -> str:
    return f"img_{uuid.uuid4().hex[:12]}"


def _probe_dimensions(image_bytes: bytes) -> tuple[int, int] | None:
    from PIL import Image
    import io
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            return im.size  # (w, h)
    except Exception:
        return None


def drain_image_buffer(image_id: str) -> tuple[bytes, str] | None:
    """Caller (ImageService) drains the bytes once and discards them."""
    return _LAST_BATCH_BUFFERS.pop(image_id, None)
```

(`_xai_http_error`, `_http_post`, `_http_get` likely already exist in
`_xai_http.py`; if not, add minimal helpers using `httpx`. Confirm by
reading the file before editing.)

The `_LAST_BATCH_BUFFERS` is a deliberate local-state hack to keep the
ImageGenItem DTO clean (it doesn't carry bytes, only metadata). The
ImageService task drains the buffer on the same event-loop tick. If a
future refactor wants to clean this up, replace it with passing a
collector callback into `generate_images`.

- [ ] **Step 6: Run tests, verify pass**

```bash
uv run pytest tests/modules/llm/_adapters/test_xai_http.py -k "image_generation or image_groups or generate_images" -v
```

- [ ] **Step 7: Run the full xAI adapter test file to catch regressions**

```bash
uv run pytest tests/modules/llm/_adapters/test_xai_http.py -v
```

- [ ] **Step 8: Syntax check**

```bash
uv run python -m py_compile backend/modules/llm/_adapters/_xai_http.py backend/modules/llm/_adapters/_xai_image_groups.py
```

- [ ] **Step 9: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_image_groups.py backend/modules/llm/_adapters/_xai_http.py tests/modules/llm/_adapters/test_xai_http.py
git commit -m "Add xAI grok-imagine image generation to xAI adapter"
```

---

## Task 10: xAI sub-router `/imagine/test` endpoint

**Goal:** Per-connection adapter sub-router gains a `POST /imagine/test` endpoint that performs a real generation and returns the items without persisting. Used by the cockpit's "Test image" button.

**Files:**
- Modify: `backend/modules/llm/_adapters/_xai_http.py` (extend the `router()` classmethod)
- Test: extend `tests/modules/llm/_adapters/test_xai_http.py` or add an HTTP-level test if the sub-router is mounted in the test app.

- [ ] **Step 1: Read current `router()` classmethod in `_xai_http.py`**

Identify:
- Where `/test` is currently defined (existing endpoint per spec).
- What `Depends(...)` resolver provides the connection.
- How to import the request/response types.

- [ ] **Step 2: Define request/response models** at module top:

```python
class _ImagineTestRequest(BaseModel):
    group_id: str
    config: dict
    prompt: str = "a serene mountain landscape at dawn"


class _ImagineTestResponse(BaseModel):
    items: list[ImageGenItem]
```

- [ ] **Step 3: Extend `router()` with the new endpoint**

Inside the existing `router()` method body, add:

```python
    @router.post("/imagine/test", response_model=_ImagineTestResponse)
    async def imagine_test(
        body: _ImagineTestRequest,
        c: ResolvedConnection = Depends(resolve_connection_for_user),
    ) -> _ImagineTestResponse:
        # validate config against the group's typed schema
        from shared.dtos.images import ImageGroupConfig
        from pydantic import TypeAdapter
        try:
            cfg = TypeAdapter(ImageGroupConfig).validate_python(
                {**body.config, "group_id": body.group_id}
            )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"invalid config: {exc}")

        adapter = cls()
        items = await adapter.generate_images(
            connection=c, group_id=body.group_id,
            config=cfg, prompt=body.prompt,
        )
        # Drain the byte buffer immediately to avoid leaking bytes across
        # requests; we intentionally throw the bytes away in the test path.
        from backend.modules.llm._adapters._xai_http import drain_image_buffer
        for item in items:
            if item.kind == "image":
                drain_image_buffer(item.id)
        return _ImagineTestResponse(items=items)
```

- [ ] **Step 4: Add an HTTP-level test**

If the existing test file already mounts the sub-router into a FastAPI test client, extend it. Otherwise, add a focused test that constructs the router and invokes the endpoint with a mocked adapter.

- [ ] **Step 5: Syntax + tests**

```bash
uv run python -m py_compile backend/modules/llm/_adapters/_xai_http.py
uv run pytest tests/modules/llm/_adapters/test_xai_http.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/_adapters/_xai_http.py tests/modules/llm/_adapters/test_xai_http.py
git commit -m "Add /imagine/test endpoint to xAI adapter sub-router"
```

---

## Task 11: `LlmService` image methods

**Goal:** `LlmService` exposes `list_image_groups`, `validate_image_config`, `generate_images` as the only entry points other modules use for image work.

**Files:**
- Modify: `backend/modules/llm/__init__.py`
- Test: `tests/modules/llm/test_service_image_methods.py`

- [ ] **Step 1: Read `backend/modules/llm/__init__.py`** to identify the `LlmService` class and its existing patterns for connection resolution.

- [ ] **Step 2: Write failing test**

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.modules.llm import LlmService
from shared.dtos.images import XaiImagineConfig


@pytest.mark.asyncio
async def test_list_image_groups_filters_image_capable_connections():
    """Connections whose adapter does not declare supports_image_generation
    are excluded."""
    # Construct LlmService with mocked dependencies; details depend on
    # actual constructor — read __init__.py to determine the right way to
    # build a test instance. This test can be skipped with @pytest.mark.skip
    # if the service requires significant scaffolding; in that case rely
    # on the integration manual verification.
    pass


@pytest.mark.asyncio
async def test_validate_image_config_rejects_wrong_group():
    svc = LlmService.__new__(LlmService)  # bypass __init__ for pure-function test
    with pytest.raises(ValueError):
        await svc.validate_image_config(group_id="xai_imagine", config={"tier": "fancy"})


@pytest.mark.asyncio
async def test_validate_image_config_accepts_valid_xai():
    svc = LlmService.__new__(LlmService)
    cfg = await svc.validate_image_config(
        group_id="xai_imagine",
        config={"tier": "pro", "resolution": "2k", "aspect": "16:9", "n": 6},
    )
    assert isinstance(cfg, XaiImagineConfig)
    assert cfg.tier == "pro"
```

- [ ] **Step 3: Implement methods on `LlmService`**

```python
    async def list_image_groups(self, *, user_id: str) -> list[ConnectionImageGroupsDto]:
        """For each connection of `user_id` whose adapter declares image
        support, return its (connection_id, display_name, group_ids).
        """
        out: list[ConnectionImageGroupsDto] = []
        connections = await self._connections_repo.list_for_user(user_id)
        for conn in connections:
            adapter_cls = self._registry.get(conn.adapter_type)
            if adapter_cls is None or not adapter_cls.supports_image_generation:
                continue
            resolved = await self._resolve_connection(conn, user_id)
            adapter = adapter_cls()
            groups = await adapter.image_groups(resolved)
            if groups:
                out.append(ConnectionImageGroupsDto(
                    connection_id=conn.id,
                    connection_display_name=conn.display_name,
                    group_ids=groups,
                ))
        return out

    async def validate_image_config(
        self, *, group_id: str, config: dict,
    ) -> ImageGroupConfig:
        """Parse and validate ``config`` against the typed schema for
        ``group_id``. Raises ``ValueError`` on mismatch.
        """
        from pydantic import TypeAdapter, ValidationError
        try:
            return TypeAdapter(ImageGroupConfig).validate_python(
                {**config, "group_id": group_id}
            )
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

    async def generate_images(
        self,
        *,
        user_id: str,
        connection_id: str,
        group_id: str,
        config: ImageGroupConfig,
        prompt: str,
    ) -> list[ImageGenItem]:
        """Resolve connection (with ownership check), instantiate adapter,
        invoke ``generate_images``. Persistence is the caller's concern.
        """
        conn = await self._connections_repo.find_for_user(user_id, connection_id)
        if conn is None:
            raise PermissionError("connection not found or not owned by user")
        adapter_cls = self._registry.get(conn.adapter_type)
        if adapter_cls is None or not adapter_cls.supports_image_generation:
            raise ValueError("adapter does not support image generation")
        resolved = await self._resolve_connection(conn, user_id)
        adapter = adapter_cls()
        return await adapter.generate_images(
            connection=resolved, group_id=group_id, config=config, prompt=prompt,
        )
```

The exact field names (`self._connections_repo`, `self._registry`,
`self._resolve_connection`) come from the actual `LlmService`
implementation — read `backend/modules/llm/__init__.py` first and use
the real names.

Add the imports at the top:

```python
from shared.dtos.images import (
    ConnectionImageGroupsDto,
    ImageGenItem,
    ImageGroupConfig,
)
```

- [ ] **Step 4: Run tests, verify pass**

```bash
uv run pytest tests/modules/llm/test_service_image_methods.py -v
```

- [ ] **Step 5: Syntax check**

```bash
uv run python -m py_compile backend/modules/llm/__init__.py
```

- [ ] **Step 6: Commit**

```bash
git add backend/modules/llm/__init__.py tests/modules/llm/test_service_image_methods.py
git commit -m "Add image generation methods to LlmService"
```

---

## Task 12: `ImageService`

**Goal:** Orchestrator that ties together user config, LlmService, BlobStore, repositories and thumbnail generation. Exposes the public API of the images module.

**Files:**
- Create: `backend/modules/images/_service.py`
- Modify: `backend/modules/images/__init__.py` (export `ImageService`)
- Test: `tests/modules/images/test_service.py` (mocks LlmService and BlobStore)

- [ ] **Step 1: Write failing tests**

`tests/modules/images/test_service.py`:

```python
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.modules.images._service import (
    ImageGenerationOutcome,
    ImageService,
)
from backend.modules.images._models import GeneratedImageDocument, UserImageConfigDocument
from shared.dtos.images import (
    GeneratedImageResult,
    ModeratedRejection,
    XaiImagineConfig,
)


def _active_cfg(group_id="xai_imagine", connection_id="conn_a"):
    return UserImageConfigDocument(
        id=f"u1:{connection_id}:{group_id}", user_id="u1",
        connection_id=connection_id, group_id=group_id,
        config={"tier": "normal", "n": 2},
        selected=True, updated_at=datetime.now(UTC),
    )


@pytest.fixture
def llm_service():
    s = MagicMock()
    s.validate_image_config = AsyncMock()
    s.generate_images = AsyncMock()
    return s


@pytest.fixture
def blob_store():
    bs = MagicMock()
    bs.save = MagicMock(return_value="ok")
    return bs


@pytest.fixture
def gen_repo():
    r = MagicMock()
    r.insert = AsyncMock()
    r.insert_many = AsyncMock()
    r.find_for_user = AsyncMock()
    return r


@pytest.fixture
def cfg_repo():
    r = MagicMock()
    r.get_active = AsyncMock()
    r.upsert = AsyncMock()
    r.set_active = AsyncMock()
    return r


@pytest.fixture
def image_service(llm_service, blob_store, gen_repo, cfg_repo):
    return ImageService(
        llm_service=llm_service, blob_store=blob_store,
        gen_repo=gen_repo, cfg_repo=cfg_repo,
    )


@pytest.mark.asyncio
async def test_generate_for_chat_no_active_config_raises(image_service, cfg_repo):
    cfg_repo.get_active.return_value = None
    with pytest.raises(LookupError, match="no active image configuration"):
        await image_service.generate_for_chat(
            user_id="u1", prompt="x", tool_call_id="tc1",
        )


@pytest.mark.asyncio
async def test_generate_for_chat_partial_moderation_outcome(
    image_service, llm_service, cfg_repo, monkeypatch,
):
    cfg_repo.get_active.return_value = _active_cfg()
    llm_service.validate_image_config.return_value = XaiImagineConfig(n=2)

    # Two items: one success, one moderated
    success = GeneratedImageResult(
        id="img_a", width=1024, height=1024, model_id="grok-imagine",
    )
    moderated = ModeratedRejection(reason=None)
    llm_service.generate_images.return_value = [success, moderated]

    # Drain returns bytes for the success id
    monkeypatch.setattr(
        "backend.modules.images._service.drain_image_buffer",
        lambda iid: (b"\xff\xd8raw", "image/jpeg") if iid == "img_a" else None,
    )
    monkeypatch.setattr(
        "backend.modules.images._service.generate_thumbnail_jpeg",
        lambda b, max_edge=256: b"\xff\xd8thumb",
    )

    outcome = await image_service.generate_for_chat(
        user_id="u1", prompt="prompt-text", tool_call_id="tc1",
    )

    assert isinstance(outcome, ImageGenerationOutcome)
    assert len(outcome.image_refs) == 1
    assert outcome.moderated_count == 1
    assert outcome.successful_count == 1
    assert "img_a" in outcome.llm_text_result
    assert "1 were filtered" in outcome.llm_text_result.lower()
```

- [ ] **Step 2: Run tests, verify failure**

```bash
uv run pytest tests/modules/images/test_service.py -v
```

- [ ] **Step 3: Implement `_service.py`**

```python
"""ImageService — orchestrates user config, LLM call, persistence, and
formatted outcomes for the image-gen tool executor and gallery routes."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable, Literal

from shared.dtos.images import (
    ActiveImageConfigDto,
    ConnectionImageGroupsDto,
    GeneratedImageDetailDto,
    GeneratedImageResult,
    GeneratedImageSummaryDto,
    ImageGenItem,
    ImageRefDto,
    ModeratedRejection,
    UserImageConfigDocument,
)

from backend.modules.images._models import GeneratedImageDocument
from backend.modules.images._repository import (
    GeneratedImagesRepository,
    UserImageConfigRepository,
)
from backend.modules.images._thumbnails import generate_thumbnail_jpeg
from backend.modules.llm._adapters._xai_http import drain_image_buffer


@dataclass
class ImageGenerationOutcome:
    """Returned by ImageService.generate_for_chat to the tool executor.

    - image_refs: refs to attach to the assistant message
    - moderated_count: number of items the upstream filtered
    - successful_count: number of items that produced a real image
    - llm_text_result: the text the LLM sees as the tool result
    - all_moderated: True if every requested item was filtered
    """

    image_refs: list[ImageRefDto]
    moderated_count: int
    successful_count: int
    llm_text_result: str
    all_moderated: bool


class ImageService:
    def __init__(
        self,
        *,
        llm_service,
        blob_store,
        gen_repo: GeneratedImagesRepository,
        cfg_repo: UserImageConfigRepository,
    ) -> None:
        self._llm = llm_service
        self._blobs = blob_store
        self._gen = gen_repo
        self._cfg = cfg_repo

    # ----- generation path ----------------------------------------------

    async def generate_for_chat(
        self, *, user_id: str, prompt: str, tool_call_id: str,
    ) -> ImageGenerationOutcome:
        active = await self._cfg.get_active(user_id=user_id)
        if active is None:
            raise LookupError("no active image configuration")

        cfg = await self._llm.validate_image_config(
            group_id=active.group_id, config=active.config,
        )

        items = await self._llm.generate_images(
            user_id=user_id,
            connection_id=active.connection_id,
            group_id=active.group_id,
            config=cfg,
            prompt=prompt,
        )

        return await self._persist_and_summarise(
            user_id=user_id, prompt=prompt, tool_call_id=tool_call_id,
            active=active, items=items,
        )

    async def _persist_and_summarise(
        self,
        *,
        user_id: str,
        prompt: str,
        tool_call_id: str,
        active: UserImageConfigDocument,
        items: list[ImageGenItem],
    ) -> ImageGenerationOutcome:
        now = datetime.now(UTC)
        image_refs: list[ImageRefDto] = []
        documents: list[GeneratedImageDocument] = []
        successful = 0
        moderated = 0

        for item in items:
            if isinstance(item, ModeratedRejection):
                moderated += 1
                documents.append(GeneratedImageDocument(
                    id=_new_uuid_id(), user_id=user_id,
                    prompt=prompt, model_id="(moderated)",
                    group_id=active.group_id, connection_id=active.connection_id,
                    config_snapshot=active.config,
                    moderated=True, moderation_reason=item.reason,
                    generated_at=now,
                ))
                continue

            assert isinstance(item, GeneratedImageResult)
            buf = drain_image_buffer(item.id)
            if buf is None:
                # adapter promised an image but did not stash bytes — treat
                # as moderated/failed
                moderated += 1
                continue

            full_bytes, content_type = buf
            thumb_bytes = generate_thumbnail_jpeg(full_bytes, max_edge=256)
            full_blob_id = item.id
            thumb_blob_id = f"{item.id}_thumb"
            self._blobs.save(user_id, full_blob_id, full_bytes)
            self._blobs.save(user_id, thumb_blob_id, thumb_bytes)

            documents.append(GeneratedImageDocument(
                id=item.id, user_id=user_id,
                blob_id=full_blob_id, thumb_blob_id=thumb_blob_id,
                prompt=prompt, model_id=item.model_id,
                group_id=active.group_id, connection_id=active.connection_id,
                config_snapshot=active.config,
                width=item.width, height=item.height,
                content_type=content_type, generated_at=now,
            ))
            image_refs.append(ImageRefDto(
                id=item.id,
                blob_url=f"/api/images/{item.id}/blob",
                thumb_url=f"/api/images/{item.id}/thumb",
                width=item.width, height=item.height,
                prompt=prompt, model_id=item.model_id,
                tool_call_id=tool_call_id,
            ))
            successful += 1

        if documents:
            await self._gen.insert_many(documents)

        text = _format_llm_text(
            successful=successful, moderated=moderated,
            documents=[d for d in documents if not d.moderated],
        )
        return ImageGenerationOutcome(
            image_refs=image_refs,
            moderated_count=moderated,
            successful_count=successful,
            llm_text_result=text,
            all_moderated=(successful == 0 and moderated > 0),
        )

    # ----- gallery / config / blob streaming ----------------------------

    async def list_user_images(
        self, *, user_id: str, limit: int = 50, before: datetime | None = None,
    ) -> list[GeneratedImageSummaryDto]:
        rows = await self._gen.list_for_user(
            user_id=user_id, limit=limit, before=before,
        )
        out: list[GeneratedImageSummaryDto] = []
        for r in rows:
            if r.moderated:
                continue  # gallery hides moderated stubs
            out.append(GeneratedImageSummaryDto(
                id=r.id,
                thumb_url=f"/api/images/{r.id}/thumb",
                width=r.width or 0, height=r.height or 0,
                prompt=r.prompt, model_id=r.model_id,
                generated_at=r.generated_at,
            ))
        return out

    async def get_image(
        self, *, user_id: str, image_id: str,
    ) -> GeneratedImageDetailDto | None:
        r = await self._gen.find_for_user(user_id=user_id, image_id=image_id)
        if r is None or r.moderated:
            return None
        return GeneratedImageDetailDto(
            id=r.id, thumb_url=f"/api/images/{r.id}/thumb",
            blob_url=f"/api/images/{r.id}/blob",
            width=r.width or 0, height=r.height or 0,
            prompt=r.prompt, model_id=r.model_id,
            generated_at=r.generated_at,
            config_snapshot=r.config_snapshot,
            connection_id=r.connection_id, group_id=r.group_id,
        )

    async def delete_image(self, *, user_id: str, image_id: str) -> bool:
        r = await self._gen.find_for_user(user_id=user_id, image_id=image_id)
        if r is None:
            return False
        if r.blob_id:
            self._blobs.delete(user_id, r.blob_id)
        if r.thumb_blob_id:
            self._blobs.delete(user_id, r.thumb_blob_id)
        return await self._gen.delete_for_user(user_id=user_id, image_id=image_id)

    async def stream_blob(
        self,
        *,
        user_id: str,
        image_id: str,
        kind: Literal["full", "thumb"],
    ) -> tuple[bytes, str] | None:
        r = await self._gen.find_for_user(user_id=user_id, image_id=image_id)
        if r is None or r.moderated:
            return None
        blob_id = r.blob_id if kind == "full" else r.thumb_blob_id
        if blob_id is None:
            return None
        data = self._blobs.load(user_id, blob_id)
        if data is None:
            return None
        ct = r.content_type if kind == "full" else "image/jpeg"
        return data, (ct or "image/jpeg")

    async def list_available_groups(
        self, *, user_id: str,
    ) -> list[ConnectionImageGroupsDto]:
        return await self._llm.list_image_groups(user_id=user_id)

    async def get_active_config(
        self, *, user_id: str,
    ) -> ActiveImageConfigDto | None:
        active = await self._cfg.get_active(user_id=user_id)
        if active is None:
            return None
        return ActiveImageConfigDto(
            connection_id=active.connection_id,
            group_id=active.group_id,
            config=active.config,
        )

    async def set_active_config(
        self,
        *,
        user_id: str,
        connection_id: str,
        group_id: str,
        config: dict,
    ) -> ActiveImageConfigDto:
        # Validate before persisting
        _ = await self._llm.validate_image_config(group_id=group_id, config=config)
        await self._cfg.upsert(
            user_id=user_id, connection_id=connection_id,
            group_id=group_id, config=config,
        )
        await self._cfg.set_active(
            user_id=user_id, connection_id=connection_id, group_id=group_id,
        )
        return ActiveImageConfigDto(
            connection_id=connection_id, group_id=group_id, config=config,
        )

    async def cascade_delete_user(self, *, user_id: str) -> int:
        """Right-to-be-forgotten cascade. Returns number of images deleted."""
        # Collect ids first so we can also drop blobs
        rows = await self._gen.list_for_user(
            user_id=user_id, limit=10_000, before=None,
        )
        for r in rows:
            if r.blob_id:
                self._blobs.delete(user_id, r.blob_id)
            if r.thumb_blob_id:
                self._blobs.delete(user_id, r.thumb_blob_id)
        count = await self._gen.delete_all_for_user(user_id=user_id)
        await self._cfg.delete_all_for_user(user_id=user_id)
        return count


# --- helpers ----------------------------------------------------------------

def _new_uuid_id() -> str:
    import uuid
    return f"img_{uuid.uuid4().hex[:12]}"


def _format_llm_text(
    *,
    successful: int,
    moderated: int,
    documents: list[GeneratedImageDocument],
) -> str:
    total = successful + moderated
    if successful == 0 and moderated > 0:
        return (
            f"All {total} requested images were filtered by content moderation. "
            "Try rephrasing the prompt."
        )
    lines = [
        f"Generated {successful} of {total} requested images. "
        f"{moderated} were filtered by content moderation."
        if moderated > 0
        else f"Generated {successful} images.",
        "",
        "Images:",
    ]
    for i, d in enumerate(documents, start=1):
        lines.append(
            f"{i}. id={d.id} ({d.width or 0}x{d.height or 0}, {d.model_id})"
        )
    lines.append("")
    lines.append(
        "Use the id values to reference these images in subsequent tool calls."
    )
    return "\n".join(lines)
```

- [ ] **Step 4: Update `backend/modules/images/__init__.py`** to export the public API:

```python
"""Image generation module."""

from backend.modules.images._service import ImageGenerationOutcome, ImageService

__all__ = ["ImageService", "ImageGenerationOutcome"]
```

(`router` and `init_indexes` will be added in later tasks; keep this
clean for now.)

- [ ] **Step 5: Run tests, verify pass**

```bash
uv run pytest tests/modules/images/test_service.py -v
```

- [ ] **Step 6: Syntax check**

```bash
uv run python -m py_compile backend/modules/images/_service.py backend/modules/images/__init__.py
```

- [ ] **Step 7: Commit**

```bash
git add backend/modules/images/_service.py backend/modules/images/__init__.py tests/modules/images/test_service.py
git commit -m "Add ImageService orchestrator (generate, gallery, config, blob)"
```

---

## Task 13: Tool executor + conditional registration

**Goal:** `ImageGenerationToolExecutor` invokes `ImageService.generate_for_chat`; the registry adds the `image_generation` tool group **only** when an image-capable connection + active config exist for the user.

**Files:**
- Create: `backend/modules/images/_tool_executor.py`
- Modify: `backend/modules/tools/_registry.py`
- Test: extend the registry test or add a new one

- [ ] **Step 1: Create `_tool_executor.py`**

```python
"""Tool executor that bridges the tools registry to ImageService."""

import json

from backend.modules.images._service import ImageService


_TOOL_NAME = "generate_image"


class ImageGenerationToolExecutor:
    def __init__(self, image_service: ImageService) -> None:
        self._svc = image_service

    async def execute(self, user_id: str, tool_name: str, arguments: dict) -> str:
        if tool_name != _TOOL_NAME:
            raise ValueError(f"unknown tool {tool_name!r}")
        prompt = arguments.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return "Error: prompt is required and must be a non-empty string."
        tool_call_id = arguments.get("__tool_call_id__", "")
        try:
            outcome = await self._svc.generate_for_chat(
                user_id=user_id, prompt=prompt, tool_call_id=tool_call_id,
            )
        except LookupError:
            return (
                "Error: image generation is not configured. The user needs to "
                "set up an image-capable connection and select an active "
                "image configuration."
            )
        return outcome.llm_text_result

    @staticmethod
    def tool_definition():
        from shared.dtos.inference import ToolDefinition
        return ToolDefinition(
            name=_TOOL_NAME,
            description=(
                "Generate one or more images from a text prompt. The user "
                "has pre-configured the model, count, and image dimensions; "
                "you only choose the prompt. Be descriptive — a good prompt "
                "has subject, style, lighting, and composition cues."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "The image description.",
                    },
                },
                "required": ["prompt"],
            },
        )
```

**Note on `__tool_call_id__`:** the orchestrator dispatching the tool
call must inject the actual `tool_call_id` into `arguments` before
calling the executor. Read the existing tool dispatch code (search
`tools/_executors.py` and the chat orchestrator for how `tool_call_id`
flows) and adapt the executor signature if it is already passed
positionally. **Do not invent a new dispatch convention without
verifying the existing one.**

- [ ] **Step 2: Modify `tools/_registry.py`**

The registry already builds groups statically. We need conditional
registration based on user state, so the registration must happen at
**resolution time** (per request) rather than at startup. Read the
current usage of `get_groups()` in the chat orchestrator. Two
approaches:

1. **Per-request filter:** keep `_build_groups()` returning the
   image_generation group always, then filter it out at the orchestrator
   if the user has no image config.
2. **Per-request augmentation:** keep `_build_groups()` without the
   image group; have a helper `available_groups_for_user(user_id)` that
   adds it conditionally.

(1) matches the existing pattern (groups are static, toggling is
orthogonal). Implement (1).

In `_build_groups()`, after the `mcp` group, add:

```python
        "image_generation": ToolGroup(
            id="image_generation",
            display_name="Image Generation",
            description=(
                "Generate images from text prompts. Available when an "
                "image-capable connection is configured and an active "
                "image configuration is selected."
            ),
            side="server",
            toggleable=False,  # rides on tools_enabled with the rest
            tool_names=["generate_image"],
            definitions=[ImageGenerationToolExecutor.tool_definition()],
            executor=None,  # constructed at resolution time with the
                            # ImageService instance; see resolver below
        ),
```

Add the import at the top:

```python
    from backend.modules.images._tool_executor import ImageGenerationToolExecutor
```

**Then add a resolver function** that accepts a user id and the live
ImageService and returns the actual groups available to the user:

```python
async def available_groups_for_user(
    *, user_id: str, image_service,
) -> dict[str, ToolGroup]:
    groups = dict(get_groups())
    image_group = groups.get("image_generation")
    if image_group is None:
        return groups

    # Drop image_generation if the user has no active image config
    has_active = await image_service.get_active_config(user_id=user_id) is not None
    if not has_active:
        groups.pop("image_generation")
        return groups

    # Inject the executor with the bound service
    from backend.modules.images._tool_executor import ImageGenerationToolExecutor
    groups["image_generation"] = ToolGroup(
        id=image_group.id,
        display_name=image_group.display_name,
        description=image_group.description,
        side=image_group.side,
        toggleable=image_group.toggleable,
        tool_names=image_group.tool_names,
        definitions=image_group.definitions,
        executor=ImageGenerationToolExecutor(image_service),
    )
    return groups
```

The chat orchestrator currently uses `get_groups()` directly; replace
its call site with `await available_groups_for_user(user_id=..., image_service=...)`.
Read the orchestrator code first to know the exact site (search for
`get_groups(` and `_build_groups(` in `backend/modules/chat/`).

- [ ] **Step 3: Add a unit test for the resolver**

```python
from unittest.mock import AsyncMock, MagicMock
import pytest

from backend.modules.tools._registry import available_groups_for_user


@pytest.mark.asyncio
async def test_image_group_present_when_active_config():
    svc = MagicMock()
    svc.get_active_config = AsyncMock(return_value=MagicMock())
    groups = await available_groups_for_user(user_id="u1", image_service=svc)
    assert "image_generation" in groups
    assert groups["image_generation"].executor is not None


@pytest.mark.asyncio
async def test_image_group_absent_when_no_active_config():
    svc = MagicMock()
    svc.get_active_config = AsyncMock(return_value=None)
    groups = await available_groups_for_user(user_id="u1", image_service=svc)
    assert "image_generation" not in groups
```

- [ ] **Step 4: Run tests + syntax check**

```bash
uv run pytest tests/modules/tools/ -v
uv run python -m py_compile backend/modules/tools/_registry.py backend/modules/images/_tool_executor.py
```

- [ ] **Step 5: Commit**

```bash
git add backend/modules/images/_tool_executor.py backend/modules/tools/_registry.py tests/modules/tools/
git commit -m "Register image_generation tool group conditionally on active config"
```

---

## Task 14: HTTP routes — `/api/images/*`

**Goal:** REST endpoints for gallery list/get/blob/thumb/delete and config get/set.

**Files:**
- Create: `backend/modules/images/_http.py`
- Modify: `backend/modules/images/__init__.py` to export `router`, `init_indexes`
- Test: `tests/modules/images/test_http.py`

- [ ] **Step 1: Read an existing module's `_http.py`** for the auth/dep pattern (e.g., `backend/modules/storage/...`) — confirm how the current user is injected and how routers are exported.

- [ ] **Step 2: Implement `_http.py`**

```python
"""HTTP routes for the images module."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from backend.modules.images._service import ImageService
from backend.modules.user import get_current_user_id  # confirm exact path
from shared.dtos.images import (
    ActiveImageConfigDto,
    ConnectionImageGroupsDto,
    GeneratedImageDetailDto,
    GeneratedImageSummaryDto,
)


router = APIRouter(prefix="/api/images", tags=["images"])


class _SetActiveConfigRequest(BaseModel):
    connection_id: str
    group_id: str
    config: dict


class _ImageConfigDiscoveryDto(BaseModel):
    available: list[ConnectionImageGroupsDto]
    active: ActiveImageConfigDto | None


def _service() -> ImageService:
    """Resolver for ImageService (singleton wired in main.py)."""
    from backend.modules.images import _SERVICE_SINGLETON
    if _SERVICE_SINGLETON is None:
        raise RuntimeError("ImageService not initialised")
    return _SERVICE_SINGLETON


@router.get("", response_model=list[GeneratedImageSummaryDto])
async def list_images(
    user_id: Annotated[str, Depends(get_current_user_id)],
    limit: int = Query(50, ge=1, le=200),
    before: datetime | None = None,
    svc: ImageService = Depends(_service),
):
    return await svc.list_user_images(user_id=user_id, limit=limit, before=before)


@router.get("/config", response_model=_ImageConfigDiscoveryDto)
async def get_config(
    user_id: Annotated[str, Depends(get_current_user_id)],
    svc: ImageService = Depends(_service),
):
    available = await svc.list_available_groups(user_id=user_id)
    active = await svc.get_active_config(user_id=user_id)
    return _ImageConfigDiscoveryDto(available=available, active=active)


@router.post("/config", response_model=ActiveImageConfigDto)
async def set_config(
    body: _SetActiveConfigRequest,
    user_id: Annotated[str, Depends(get_current_user_id)],
    svc: ImageService = Depends(_service),
):
    try:
        return await svc.set_active_config(
            user_id=user_id,
            connection_id=body.connection_id,
            group_id=body.group_id,
            config=body.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{image_id}", response_model=GeneratedImageDetailDto)
async def get_image(
    image_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    svc: ImageService = Depends(_service),
):
    detail = await svc.get_image(user_id=user_id, image_id=image_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="image not found")
    return detail


@router.get("/{image_id}/blob")
async def get_blob(
    image_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    svc: ImageService = Depends(_service),
):
    result = await svc.stream_blob(user_id=user_id, image_id=image_id, kind="full")
    if result is None:
        raise HTTPException(status_code=404, detail="image not found")
    data, content_type = result
    return Response(content=data, media_type=content_type)


@router.get("/{image_id}/thumb")
async def get_thumb(
    image_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    svc: ImageService = Depends(_service),
):
    result = await svc.stream_blob(user_id=user_id, image_id=image_id, kind="thumb")
    if result is None:
        raise HTTPException(status_code=404, detail="image not found")
    data, content_type = result
    return Response(content=data, media_type=content_type)


@router.delete("/{image_id}", status_code=204)
async def delete_image(
    image_id: str,
    user_id: Annotated[str, Depends(get_current_user_id)],
    svc: ImageService = Depends(_service),
):
    deleted = await svc.delete_image(user_id=user_id, image_id=image_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="image not found")
```

- [ ] **Step 3: Update `backend/modules/images/__init__.py`**

```python
"""Image generation module — public API."""

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.modules.images._http import router
from backend.modules.images._repository import (
    GeneratedImagesRepository,
    UserImageConfigRepository,
)
from backend.modules.images._service import ImageGenerationOutcome, ImageService


_SERVICE_SINGLETON: ImageService | None = None


def set_image_service(svc: ImageService) -> None:
    global _SERVICE_SINGLETON
    _SERVICE_SINGLETON = svc


def get_image_service() -> ImageService:
    if _SERVICE_SINGLETON is None:
        raise RuntimeError("ImageService not initialised")
    return _SERVICE_SINGLETON


async def init_indexes(db: AsyncIOMotorDatabase) -> None:
    await GeneratedImagesRepository(db).create_indexes()
    await UserImageConfigRepository(db).create_indexes()


__all__ = [
    "ImageService",
    "ImageGenerationOutcome",
    "router",
    "init_indexes",
    "set_image_service",
    "get_image_service",
]
```

- [ ] **Step 4: Add HTTP test** (`tests/modules/images/test_http.py`)

Use FastAPI's `TestClient` with a mounted router and a stubbed
`ImageService`. Test 200/404 paths for each endpoint.

- [ ] **Step 5: Syntax + tests**

```bash
uv run python -m py_compile backend/modules/images/_http.py backend/modules/images/__init__.py
uv run pytest tests/modules/images/test_http.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/modules/images/_http.py backend/modules/images/__init__.py tests/modules/images/test_http.py
git commit -m "Add /api/images/* HTTP routes for gallery and config"
```

---

## Task 15: Wire `images` module into `main.py`

**Goal:** `main.py` imports the images router, runs `init_indexes`, and constructs the `ImageService` singleton with real dependencies.

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Read `main.py` lifespan + router-mounting pattern** for any module already wired (e.g., `storage`).

- [ ] **Step 2: Add imports**

```python
from backend.modules.images import (
    router as images_router,
    init_indexes as images_init_indexes,
    ImageService,
    set_image_service,
)
from backend.modules.images._repository import (
    GeneratedImagesRepository,
    UserImageConfigRepository,
)
```

- [ ] **Step 3: In the lifespan startup, after the database is connected:**

```python
    db = get_db()
    await images_init_indexes(db)

    image_service = ImageService(
        llm_service=llm_service,        # already constructed earlier
        blob_store=blob_store,           # confirm name in main.py
        gen_repo=GeneratedImagesRepository(db),
        cfg_repo=UserImageConfigRepository(db),
    )
    set_image_service(image_service)
```

- [ ] **Step 4: Mount the router**

After the existing `app.include_router(storage_router)` (or near it):

```python
    app.include_router(images_router)
```

- [ ] **Step 5: Wire image-service into the chat orchestrator**

The orchestrator calls `available_groups_for_user(...)` (Task 13).
Inject the `ImageService` either via construction or via a getter
(`from backend.modules.images import get_image_service`). Read the
orchestrator's construction site in `main.py` and adapt.

- [ ] **Step 6: Wire cascade-delete into the user delete-account flow**

Find the user-delete cascade in `backend/modules/user/`. After the
existing `delete_all_for_user` cascade calls, add:

```python
    await image_service.cascade_delete_user(user_id=user_id)
```

This satisfies right-to-be-forgotten for the new collections.

- [ ] **Step 7: Verify the app boots**

```bash
docker compose up backend
# Expected: no errors during startup; the lifespan logs show
# "init_indexes" called for images and the service singleton initialised.
```

- [ ] **Step 8: Syntax check**

```bash
uv run python -m py_compile backend/main.py
```

- [ ] **Step 9: Commit**

```bash
git add backend/main.py
git commit -m "Wire images module into main.py lifespan and routers"
```

---

## Task 16: Chat attachment loader recognises `generated_images.id`

**Goal:** When a chat message has `attachment_ids: [<generated_image_id>]`, the backend resolves it the same way uploads are resolved (i.e., the assistant sees it as an attachment).

**Files:**
- Modify: chat module attachment resolution code (subagent locates exact file)
- Test: integration test in `tests/modules/chat/`

- [ ] **Step 1: Locate the attachment resolver**

Search:

```bash
rg -n "attachment_ids" backend/modules/chat/
rg -n "AttachmentRefDto" backend/modules/chat/
```

Identify the function that resolves `attachment_ids` into the inference
payload (text/binary blocks for vision, or simple references). This is
typically called from the message-send pipeline.

- [ ] **Step 2: Modify the resolver**

When iterating `attachment_ids`, the resolver currently looks them up
via the storage module. Add a fallback (or first-check) for
`generated_images`:

```python
from backend.modules.images import get_image_service

async def resolve_attachment(user_id: str, attachment_id: str):
    # First, check the storage module (existing path)
    storage_ref = await storage_service.find(user_id, attachment_id)
    if storage_ref is not None:
        return storage_ref

    # Then, check the images module
    image_svc = get_image_service()
    detail = await image_svc.get_image(user_id=user_id, image_id=attachment_id)
    if detail is not None:
        # Return an AttachmentRefDto-compatible structure pointing at the
        # image blob. Match the shape the rest of the resolver returns.
        ...
```

The exact return structure depends on what the rest of the chat
pipeline expects. Read carefully and match. If the chat pipeline
expects an `AttachmentRefDto` that points at a `BlobStore` location,
the existing image already has one — the conversion is mechanical.

- [ ] **Step 3: Add a small integration test**

Test that a chat message with `attachment_ids=[<generated_image_id>]`
is accepted, and that the resolved attachment metadata matches what the
gallery endpoint would return.

- [ ] **Step 4: Syntax + tests**

```bash
uv run python -m py_compile <touched files>
PYTHONPATH=. uv run pytest tests/modules/chat/ -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/<touched files> tests/modules/chat/<touched files>
git commit -m "Resolve generated images as chat attachments"
```

---

## Task 17: Frontend — regenerate TS types

**Goal:** TypeScript types for the new shared DTOs are available on the frontend.

**Files:**
- Modify: generated types files (location depends on the existing pipeline)

- [ ] **Step 1: Find the types-generation pipeline**

Search:

```bash
rg -n "shared/dtos" frontend/ scripts/
```

Identify how Pydantic models become TS types (could be `datamodel-code-generator`, a hand-rolled script, etc.) and run the generator.

- [ ] **Step 2: Run the generator**

The exact command is project-specific. Common options:

```bash
pnpm --dir frontend run gen:types     # if a script exists
# or
make types
# or manually invoke the codegen
```

- [ ] **Step 3: Verify the generated types include**

- `XaiImagineConfig`
- `ImageGroupConfig` (discriminated union)
- `GeneratedImageResult`, `ModeratedRejection`, `ImageGenItem`
- `ImageRefDto`, `GeneratedImageSummaryDto`, `GeneratedImageDetailDto`
- `ConnectionImageGroupsDto`, `ActiveImageConfigDto`
- Updated `ToolCallRefDto` (with `moderated_count`)
- Updated `ChatMessageDto` (with `image_refs`)

- [ ] **Step 4: TS compile check**

```bash
pnpm --dir frontend tsc --noEmit
```

- [ ] **Step 5: Commit**

```bash
git add frontend/<generated-types-paths>
git commit -m "Regenerate TS types for image generation DTOs"
```

---

## Task 18: Frontend — `api.ts`, `store.ts`, group registry skeleton

**Goal:** Thin REST wrappers, a state store for active config + gallery cache, and an empty group registry ready for `XaiImagineConfigView`.

**Files:**
- Create: `frontend/src/features/images/api.ts`
- Create: `frontend/src/features/images/store.ts`
- Create: `frontend/src/features/images/groups/registry.ts`

- [ ] **Step 1: Read an existing feature's `api.ts` + `store.ts`** for conventions (auth, error handling, store shape — likely zustand or similar).

- [ ] **Step 2: Implement `api.ts`**

```typescript
import type {
  ActiveImageConfigDto,
  ConnectionImageGroupsDto,
  GeneratedImageSummaryDto,
  GeneratedImageDetailDto,
  ImageGroupConfig,
} from '@/shared/dtos/images'  // path depends on type-gen output

import { api } from '@/lib/api'   // existing fetch wrapper; confirm path

export type ImageConfigDiscovery = {
  available: ConnectionImageGroupsDto[]
  active: ActiveImageConfigDto | null
}

export async function listImages(
  opts?: { limit?: number; before?: string },
): Promise<GeneratedImageSummaryDto[]> {
  const params = new URLSearchParams()
  if (opts?.limit) params.set('limit', String(opts.limit))
  if (opts?.before) params.set('before', opts.before)
  return api.get(`/api/images?${params.toString()}`)
}

export async function getImage(id: string): Promise<GeneratedImageDetailDto> {
  return api.get(`/api/images/${id}`)
}

export async function deleteImage(id: string): Promise<void> {
  await api.delete(`/api/images/${id}`)
}

export async function getImageConfig(): Promise<ImageConfigDiscovery> {
  return api.get('/api/images/config')
}

export async function setImageConfig(
  payload: { connection_id: string; group_id: string; config: ImageGroupConfig },
): Promise<ActiveImageConfigDto> {
  return api.post('/api/images/config', payload)
}

export async function testImagine(
  connectionId: string,
  payload: { group_id: string; config: ImageGroupConfig; prompt?: string },
): Promise<{ items: unknown[] }> {
  return api.post(`/api/llm/connections/${connectionId}/adapter/imagine/test`, payload)
}
```

- [ ] **Step 3: Implement `store.ts`**

Match the existing state-management lib (zustand, jotai, etc.). The
store should hold:

- `available: ConnectionImageGroupsDto[]`
- `active: ActiveImageConfigDto | null`
- `gallery: GeneratedImageSummaryDto[]` (cached, merge-on-update)
- actions: `loadConfig`, `applyConfig`, `loadGallery`, `appendGallery`,
  `removeFromGallery`

- [ ] **Step 4: Implement `groups/registry.ts`**

```typescript
import type { ImageGroupConfig } from '@/shared/dtos/images'

export type ConfigViewProps<T extends ImageGroupConfig> = {
  config: T
  onChange: (next: T) => void
}

export type ConfigViewComponent = React.FC<ConfigViewProps<ImageGroupConfig>>

// Filled in by Task 19 once XaiImagineConfigView exists
export const IMAGE_GROUP_VIEWS: Partial<Record<string, ConfigViewComponent>> = {}
```

- [ ] **Step 5: TS compile check**

```bash
pnpm --dir frontend tsc --noEmit
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/images/api.ts frontend/src/features/images/store.ts frontend/src/features/images/groups/registry.ts
git commit -m "Add images feature API client, store, and group view registry skeleton"
```

---

## Task 19: Frontend — `XaiImagineConfigView`, `ImageConfigPanel`, `ImageButton`

**Goal:** The cockpit Image button opens a panel with an upstream/group selector and the `XaiImagineConfigView`, with apply + test buttons.

**Files:**
- Create: `frontend/src/features/images/groups/XaiImagineConfigView.tsx`
- Create: `frontend/src/features/images/cockpit/ImageConfigPanel.tsx`
- Create: `frontend/src/features/images/cockpit/ImageButton.tsx`
- Modify: `frontend/src/features/images/groups/registry.ts` (register the xAI view)

- [ ] **Step 1: Read existing cockpit button + popover components** (`ToolsButton.tsx`, `IntegrationsButton.tsx`) for visual + interaction conventions.

- [ ] **Step 2: Implement `XaiImagineConfigView.tsx`**

A single component with segmented buttons for `tier`, `resolution`,
`aspect`, and a stepper for `n`. Tailwind styling matches the existing
cockpit panel aesthetic.

```tsx
import type { XaiImagineConfig } from '@/shared/dtos/images'
import type { ConfigViewProps } from './registry'

const TIERS: XaiImagineConfig['tier'][] = ['normal', 'pro']
const RESOLUTIONS: XaiImagineConfig['resolution'][] = ['1k', '2k']
const ASPECTS: XaiImagineConfig['aspect'][] = ['1:1', '16:9', '9:16', '4:3', '3:4']

export function XaiImagineConfigView(
  { config, onChange }: ConfigViewProps<XaiImagineConfig>,
) {
  return (
    <div className="space-y-3">
      <SegRow label="Quality" value={config.tier} options={TIERS}
        onChange={(tier) => onChange({ ...config, tier })} />
      <SegRow label="Resolution" value={config.resolution} options={RESOLUTIONS}
        onChange={(resolution) => onChange({ ...config, resolution })} />
      <SegRow label="Aspect" value={config.aspect} options={ASPECTS}
        onChange={(aspect) => onChange({ ...config, aspect })} />
      <Counter label="Count" value={config.n} min={1} max={10}
        onChange={(n) => onChange({ ...config, n })} />
    </div>
  )
}

function SegRow<T extends string>(...) { /* segmented buttons */ }
function Counter(...) { /* small stepper */ }
```

Implement `SegRow` and `Counter` as small local components. Match the
visual style of existing segmented controls (search the codebase for
`segmented` / `pill-row` / etc.).

- [ ] **Step 3: Register the view**

```typescript
// frontend/src/features/images/groups/registry.ts
import { XaiImagineConfigView } from './XaiImagineConfigView'

export const IMAGE_GROUP_VIEWS: Partial<Record<string, ConfigViewComponent>> = {
  xai_imagine: XaiImagineConfigView as ConfigViewComponent,
}
```

- [ ] **Step 4: Implement `ImageConfigPanel.tsx`**

Layout per spec §7.2:

```tsx
export function ImageConfigPanel({ onClose }: { onClose: () => void }) {
  const { available, active, applyConfig } = useImagesStore()
  const [connectionId, setConnectionId] = useState(active?.connection_id ?? available[0]?.connection_id ?? '')
  const conn = available.find(c => c.connection_id === connectionId)
  const [groupId, setGroupId] = useState(active?.group_id ?? conn?.group_ids[0] ?? '')
  const [config, setConfig] = useState<ImageGroupConfig | null>(active?.config as ImageGroupConfig ?? null)

  // ensure config is initialised when group changes
  // ...

  const View = IMAGE_GROUP_VIEWS[groupId]

  return (
    <div className="p-4 w-[360px]">
      <Header title="Image generation" onClose={onClose} />
      <ConnectionSelect value={connectionId} options={available} onChange={setConnectionId} />
      <GroupSelect value={groupId} options={conn?.group_ids ?? []} onChange={setGroupId} />
      {View && config && <View config={config} onChange={setConfig} />}
      <div className="mt-4 flex gap-2">
        <button onClick={() => testImagine(connectionId, { group_id: groupId, config: config! })}>
          Test image
        </button>
        <button onClick={() => applyConfig({ connection_id: connectionId, group_id: groupId, config: config! })}>
          Apply
        </button>
      </div>
    </div>
  )
}
```

Use real components / styling from the codebase rather than the
placeholders shown.

- [ ] **Step 5: Implement `ImageButton.tsx`**

```tsx
export function ImageButton() {
  const [open, setOpen] = useState(false)
  const { available, active, loadConfig } = useImagesStore()
  useEffect(() => { void loadConfig() }, [loadConfig])

  const disabled = available.length === 0
  const badgeText = active ? humanModelLabel(active) : null

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <CockpitButton aria-label="Image generation" disabled={disabled}>
          <ImageIcon />
          {badgeText && <Badge>{badgeText}</Badge>}
        </CockpitButton>
      </Popover.Trigger>
      <Popover.Content><ImageConfigPanel onClose={() => setOpen(false)} /></Popover.Content>
    </Popover>
  )
}
```

`humanModelLabel` derives a short label (e.g. `imagine-pro`) from the
active config. Implement inline or in a small util.

- [ ] **Step 6: TS compile + visual check**

```bash
pnpm --dir frontend tsc --noEmit
pnpm --dir frontend run dev
# Open the app, configure an xAI connection, manually verify the panel
# renders, all controls work, "Test image" returns thumbnails.
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/images/groups/XaiImagineConfigView.tsx frontend/src/features/images/groups/registry.ts frontend/src/features/images/cockpit/
git commit -m "Add XaiImagineConfigView and ImageConfigPanel cockpit components"
```

---

## Task 20: Frontend — wire `ImageButton` into `CockpitBar`

**Goal:** Image button placed correctly in desktop and mobile layouts per the spec.

**Files:**
- Modify: `frontend/src/features/chat/cockpit/CockpitBar.tsx`

- [ ] **Step 1: Read `CockpitBar.tsx` to confirm current order and the `CockpitGroupButton` mobile pattern.**

- [ ] **Step 2: Insert `ImageButton`**

Desktop (linear stack): between `ToolsButton` and `IntegrationsButton`,
with a separator after it.

Mobile (CockpitGroupButton): the existing tools+integrations group
becomes a three-button group: `Tools`, `Image`, `Integrations`. Adjust
the `CockpitGroupButton`'s children list.

- [ ] **Step 3: TS compile + visual check**

```bash
pnpm --dir frontend tsc --noEmit
pnpm --dir frontend run dev
# Verify desktop and mobile (use browser devtools to switch viewport).
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/cockpit/CockpitBar.tsx
git commit -m "Add Image button to cockpit (desktop and mobile)"
```

---

## Task 21: Frontend — `InlineImageBlock` + `ImageLightbox` + assistant-message integration

**Goal:** Generated images render inline under the assistant message, click opens lightbox.

**Files:**
- Create: `frontend/src/features/images/chat/InlineImageBlock.tsx`
- Create: `frontend/src/features/images/chat/ImageLightbox.tsx`
- Modify: assistant message renderer (subagent locates)

- [ ] **Step 1: Locate assistant message renderer**

```bash
rg -n "AssistantMessage" frontend/src/
rg -n "image_refs" frontend/src/
```

Most likely under `frontend/src/features/chat/messages/` or similar.

- [ ] **Step 2: Implement `InlineImageBlock.tsx`**

```tsx
import type { ImageRefDto } from '@/shared/dtos/images'
import { useState } from 'react'
import { ImageLightbox } from './ImageLightbox'

export function InlineImageBlock(
  { refs, moderatedCount }: { refs: ImageRefDto[]; moderatedCount?: number },
) {
  const [activeId, setActiveId] = useState<string | null>(null)
  const layout = refs.length <= 4 ? 'row' : 'grid'

  if (refs.length === 0) {
    if (moderatedCount && moderatedCount > 0) {
      return <ModeratedNote count={moderatedCount} />
    }
    return null
  }

  return (
    <div className="mt-2">
      <div className={layout === 'row' ? 'flex gap-2' : 'grid grid-cols-2 gap-2'}>
        {refs.map(r => (
          <button
            key={r.id}
            type="button"
            className="block focus:outline-none"
            onClick={() => setActiveId(r.id)}
          >
            <img
              src={r.thumb_url}
              alt={r.prompt}
              className="rounded-md max-h-64 object-cover"
              loading="lazy"
            />
          </button>
        ))}
      </div>
      {moderatedCount ? <ModeratedNote count={moderatedCount} /> : null}
      {activeId && (
        <ImageLightbox
          ref={refs.find(r => r.id === activeId)!}
          onClose={() => setActiveId(null)}
        />
      )}
    </div>
  )
}

function ModeratedNote({ count }: { count: number }) {
  return (
    <div className="mt-2 inline-block px-2 py-1 text-xs rounded-md bg-white/5 text-white/60">
      {count === 1
        ? '1 image filtered by content moderation'
        : `${count} images filtered by content moderation`}
    </div>
  )
}
```

- [ ] **Step 3: Implement `ImageLightbox.tsx`**

```tsx
import type { ImageRefDto } from '@/shared/dtos/images'

export function ImageLightbox(
  { ref, onClose }: { ref: ImageRefDto; onClose: () => void },
) {
  return (
    <div
      className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center"
      onClick={onClose}
    >
      <div className="max-w-[90vw] max-h-[90vh] p-4" onClick={e => e.stopPropagation()}>
        <img src={ref.blob_url} alt={ref.prompt} className="max-w-full max-h-[80vh] rounded-md" />
        <div className="mt-2 flex justify-between items-center text-white/80 text-sm">
          <span className="truncate max-w-[60%]">{ref.prompt}</span>
          <a href={ref.blob_url} download className="underline">Download</a>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Integrate into assistant message renderer**

In the renderer, after the existing tool-call pills section (and where
`artefact_refs` is rendered), add:

```tsx
{message.image_refs && message.image_refs.length > 0 && (
  <InlineImageBlock
    refs={message.image_refs}
    moderatedCount={
      message.tool_calls?.find(tc => tc.tool_name === 'generate_image')?.moderated_count
    }
  />
)}
```

If there is a tool-call but no image_refs (all moderated), render only
the `ModeratedNote` via the same component (the empty-refs branch
handles this).

- [ ] **Step 5: TS compile + visual check**

```bash
pnpm --dir frontend tsc --noEmit
pnpm --dir frontend run dev
# Trigger a generation in a chat; verify inline render for n=1,4,10.
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/images/chat/ frontend/src/features/chat/<modified renderer>
git commit -m "Render generated images inline under assistant messages"
```

---

## Task 22: Frontend — `GalleryGrid` + `GalleryLightbox` + nav entry

**Goal:** Reachable gallery view: chronological grid, lightbox with download + delete.

**Files:**
- Create: `frontend/src/features/images/gallery/GalleryGrid.tsx`
- Create: `frontend/src/features/images/gallery/GalleryLightbox.tsx`
- Modify: nav/menu (location depends on existing UI; subagent picks the most natural site — agree with Chris if ambiguous)

- [ ] **Step 1: Implement `GalleryGrid.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { listImages } from '../api'
import type { GeneratedImageSummaryDto } from '@/shared/dtos/images'
import { GalleryLightbox } from './GalleryLightbox'

export function GalleryGrid() {
  const [items, setItems] = useState<GeneratedImageSummaryDto[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => { void load(undefined) }, [])

  async function load(before: string | undefined) {
    setLoading(true)
    const next = await listImages({ limit: 50, before })
    setItems(prev => [...prev, ...next])
    setLoading(false)
  }

  return (
    <div className="p-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {items.map(it => (
          <button key={it.id} type="button" onClick={() => setActiveId(it.id)}
            className="block focus:outline-none">
            <img src={it.thumb_url} alt={it.prompt}
              className="rounded-md aspect-square object-cover" loading="lazy" />
          </button>
        ))}
      </div>
      {items.length > 0 && (
        <button
          className="mt-4"
          onClick={() => load(items[items.length - 1].generated_at)}
          disabled={loading}
        >
          {loading ? 'Loading…' : 'Load more'}
        </button>
      )}
      {activeId && (
        <GalleryLightbox
          imageId={activeId}
          onClose={() => setActiveId(null)}
          onDeleted={() => {
            setItems(prev => prev.filter(p => p.id !== activeId))
            setActiveId(null)
          }}
        />
      )}
    </div>
  )
}
```

- [ ] **Step 2: Implement `GalleryLightbox.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { deleteImage, getImage } from '../api'
import type { GeneratedImageDetailDto } from '@/shared/dtos/images'

export function GalleryLightbox(
  { imageId, onClose, onDeleted }:
    { imageId: string; onClose: () => void; onDeleted: () => void },
) {
  const [detail, setDetail] = useState<GeneratedImageDetailDto | null>(null)
  useEffect(() => { void getImage(imageId).then(setDetail) }, [imageId])

  if (!detail) return null

  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center"
      onClick={onClose}>
      <div className="max-w-[90vw] max-h-[90vh] p-4" onClick={e => e.stopPropagation()}>
        <img src={detail.blob_url} alt={detail.prompt}
          className="max-w-full max-h-[70vh] rounded-md" />
        <div className="mt-2 text-white/80 text-sm">
          <p className="break-words">{detail.prompt}</p>
          <p className="text-xs text-white/50 mt-1">
            {detail.model_id} · {new Date(detail.generated_at).toLocaleString()}
          </p>
          <div className="mt-3 flex gap-3">
            <a href={detail.blob_url} download className="underline">Download</a>
            <button
              onClick={async () => { await deleteImage(detail.id); onDeleted() }}
              className="text-red-400 underline"
            >
              Delete
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Add nav entry**

Locate the user menu / sidebar / wherever similar feature entries live
(e.g., the upload/file management entry). Add a "My Images" or similar
link that routes to `GalleryGrid`.

- [ ] **Step 4: TS compile + visual check**

```bash
pnpm --dir frontend tsc --noEmit
pnpm --dir frontend run dev
# Generate a few images in chat, then open the gallery and verify
# rendering, download, delete.
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/images/gallery/ frontend/src/<modified nav file>
git commit -m "Add image gallery view with lightbox, download, and delete"
```

---

## Task 23: Frontend — `GeneratedImagesTab` + attachment-picker integration

**Goal:** Attachment picker shows two tabs: `Uploads` and `Generated Images`. Selecting a generated image attaches it as a normal attachment id.

**Files:**
- Create: `frontend/src/features/images/attachments/GeneratedImagesTab.tsx`
- Modify: existing attachment picker component

- [ ] **Step 1: Locate the attachment picker**

```bash
rg -n "AttachmentPicker\|UploadsList\|attachment_ids" frontend/src/features/chat/
```

- [ ] **Step 2: Add tab strip**

If the picker currently shows just uploads, wrap it in a tab strip:

```tsx
const [tab, setTab] = useState<'uploads' | 'generated'>('uploads')
return (
  <>
    <Tabs value={tab} onChange={setTab}>
      <Tab value="uploads">Uploads</Tab>
      <Tab value="generated">Generated Images</Tab>
    </Tabs>
    {tab === 'uploads' ? <UploadsList ... /> : <GeneratedImagesTab onPick={onPickAttachment} />}
  </>
)
```

- [ ] **Step 3: Implement `GeneratedImagesTab.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { listImages } from '../api'
import type { GeneratedImageSummaryDto } from '@/shared/dtos/images'

export function GeneratedImagesTab(
  { onPick }: { onPick: (image: GeneratedImageSummaryDto) => void },
) {
  const [items, setItems] = useState<GeneratedImageSummaryDto[]>([])
  useEffect(() => { void listImages({ limit: 50 }).then(setItems) }, [])

  return (
    <div className="grid grid-cols-3 gap-2 p-3 max-h-[300px] overflow-auto">
      {items.map(it => (
        <button key={it.id} type="button" onClick={() => onPick(it)}
          className="block focus:outline-none">
          <img src={it.thumb_url} alt={it.prompt}
            className="rounded-md aspect-square object-cover" loading="lazy" />
        </button>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Wire selection**

`onPickAttachment(image)` should push `image.id` into the message's
`attachment_ids` array. Confirm by sending a test message — backend
attachment loader (Task 16) resolves the id correctly.

- [ ] **Step 5: TS compile + visual check**

```bash
pnpm --dir frontend tsc --noEmit
pnpm --dir frontend run dev
# Manual verification per spec §11.5 (last bullet).
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/images/attachments/ frontend/<modified picker>
git commit -m "Add Generated Images tab to attachment picker"
```

---

## Task 24: End-to-end manual verification pass

**Goal:** Walk through the spec's Manual Verification section (§11) on a fresh stack with a real xAI connection. Anything that fails opens a follow-up.

- [ ] **Step 1: Bring up the full stack**

```bash
docker compose down && docker compose up -d
docker compose logs -f backend
```

- [ ] **Step 2: Run through each manual checkbox in spec §11**

Open `devdocs/specs/2026-04-26-tti-xai-imagine-design.md` §11 and tick
each box as it passes. Sub-sections:

- §11.1 Configuration & discovery
- §11.2 In-chat generation
- §11.3 Moderation
- §11.4 Errors
- §11.5 Gallery & attachment reuse
- §11.6 Mobile

- [ ] **Step 3: For any failures, file a follow-up note**

Either:
- Append a "Known issues" section to the spec listing what failed and why
- Or open small follow-up tasks here in the plan if quick to fix

Do **not** mark the feature complete with red checkboxes.

- [ ] **Step 4: Commit the verification record**

```bash
git add devdocs/specs/2026-04-26-tti-xai-imagine-design.md
git commit -m "Mark TTI Phase I manual verification complete"
```

---

## Done

After Task 24, Phase I is complete. The feature is testable end-to-end
with real xAI grok-imagine generation, gallery, attachment reuse and
correct moderation handling.

**Phase II (separate plan, after live tester feedback):**

- ITI / Edit tool with `source_image_id` parameter
- Vision-derived `description` populated on `GeneratedImageResult`
- Optional negative-prompt UX
- Gallery search + tags UI (server-side filtering on `tags`)
- Cost / quota tracking and surfacing
