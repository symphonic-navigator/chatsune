# Text-to-Image (TTI) via xAI grok-imagine — Phase I Design

**Date:** 2026-04-26
**Status:** Draft, awaiting Chris's review
**Phase:** I (TTI only); ITI / Edit explicitly deferred to Phase II
**Pilot upstream:** xAI grok-imagine (normal + pro)

---

## 1. Overview

Chatsune currently offers text inference, TTS and STT through the per-user
Connection model in `modules/llm/`. This spec adds a third LLM-driven
capability: text-to-image generation. xAI is the pilot upstream because the
adapter, encryption and sub-router pattern already exist
(`backend/modules/llm/_adapters/_xai_http.py`), the API surface is small,
and grok-imagine is cheap enough to make per-user BYOK economically painless.

The feature is exposed as an LLM tool (`generate_image`) that the model
calls during a conversation. Generated images appear inline under the
assistant message and are persisted in a per-user gallery. The user controls
the upstream, model group and per-call parameters from a dedicated Image
panel in the cockpit; the LLM only chooses the prompt.

Image-to-Image / edit is **out of scope** for Phase I. The disambiguation
problem ("which image do I edit?") is non-trivial and warrants its own
design pass once TTI is in production. The data model, tool result shape
and message DTO additions in this spec are deliberately structured so ITI
becomes a pure addition rather than a breaking change.

---

## 2. Scope

### In Phase I

- `modules/images/` module with `ImageService`, `UserImageConfigRepository`
  and `generated_images` collection.
- xAI grok-imagine adapter extension (image groups, image generation
  endpoint, sub-router test endpoint).
- `generate_image(prompt)` tool registered via `modules/tools/`, exposed
  through the existing `tools_enabled` session toggle.
- Cockpit Image-Panel button (desktop and mobile variants).
- Per-group typed configuration with discriminated-union DTOs in `shared/`.
- Inline rendering of generated images under the assistant message,
  including a lightbox.
- Server-side JPG thumbnails (256 px long edge).
- Gallery view: scrollable chronological grid, lightbox preview, download
  button, delete button.
- Attachment picker: new "Generated Images" tab alongside "Uploads".
- Per-image moderation handling (xAI's `respect_moderation` pattern).
- Reuse of existing `CHAT_TOOL_CALL_STARTED/COMPLETED` events; new error
  codes only.

### Explicitly out of Phase I

- ITI / Edit (Phase II — design hooks only).
- Negative prompts.
- Cost or quota tracking UI.
- Gallery search, full-text on prompt, tag UI (the `tags` field is added
  to the data model now as an E2EE-readiness placeholder, but no UI).
- Multi-tenant cost attribution beyond what BYOK already implies.
- Image-aware conversation context for non-vision models (the LLM sees
  IDs and counts, not pixels).

---

## 3. Architecture

### 3.1 Module layout

```
backend/modules/
  images/                              ← NEW
    __init__.py                        ← public API: ImageService
    _service.py                        ← ImageService implementation
    _repository.py                     ← GeneratedImagesRepository, UserImageConfigRepository
    _models.py                         ← MongoDB document types
    _thumbnails.py                     ← JPG thumbnail generation (Pillow)
    _tool_executor.py                  ← ImageGenerationToolExecutor (registered by tools/)
    _http.py                           ← FastAPI router for /api/images/...
  llm/
    _adapters/_xai_http.py             ← extended: image_groups(), generate_images(), sub-router /imagine endpoint
    _adapters/_base.py                 ← extended: optional image group declaration on BaseAdapter
    __init__.py                        ← extended: LlmService.list_image_groups, LlmService.generate_images, LlmService.validate_image_config
  tools/
    _registry.py                       ← extended: image-gen ToolGroup registration
  storage/                             ← unchanged; reused as blob layer
shared/
  dtos/images.py                       ← NEW: ImageGroupConfig discriminated union, ImageRefDto, GeneratedImageResult, ModeratedRejection
  topics.py                            ← unchanged for Phase I (reuses CHAT_TOOL_CALL_*)
frontend/src/features/
  images/                              ← NEW
    groups/
      registry.ts                      ← group_id -> ConfigView component map
      XaiImagineConfigView.tsx
    gallery/
      GalleryGrid.tsx
      GalleryLightbox.tsx
    cockpit/
      ImageButton.tsx                  ← cockpit entry point + popover
      ImageConfigPanel.tsx             ← upstream/group selector + group view host
    chat/
      InlineImageBlock.tsx             ← rendered under assistant messages
      ImageLightbox.tsx                ← shared lightbox component
    attachments/
      GeneratedImagesTab.tsx           ← new tab in attachment picker
```

### 3.2 Module boundaries

Following the strict rule from CLAUDE.md ("each module exposes exactly one
public API via its `__init__.py`"):

- `modules/images/` is the only module that touches the `generated_images`
  and `user_image_configs` collections.
- `modules/images/` calls `modules/llm/` exclusively through `LlmService`
  to perform actual generation.
- `modules/llm/` calls `modules/storage/` (BlobStore) only — never reaches
  back into `modules/images/`.
- `modules/tools/` registers the image-gen ToolGroup and constructs the
  executor with an injected `ImageService` reference. The executor
  delegates all real work to `ImageService`.
- `shared/dtos/images.py` and the (existing) `shared/topics.py` are the
  only shared contracts; no module defines its own image DTOs.

### 3.3 Adapter capability declaration

`modules/llm/_adapters/_base.py` gets an optional class-level attribute:

```python
class BaseAdapter:
    supports_image_generation: ClassVar[bool] = False
    # ... existing methods ...

    def image_groups(self) -> list[str]:
        """Return image-group ids supported by this adapter for this connection."""
        return []

    async def generate_images(
        self,
        group_id: str,
        config: ImageGroupConfig,
        prompt: str,
    ) -> list[ImageGenItem]:
        """Generate images. Default raises NotImplementedError."""
        raise NotImplementedError
```

The xAI adapter sets `supports_image_generation = True` and implements
both methods. Adapters that don't support images need no changes.

---

## 4. Data model

### 4.1 `generated_images` collection

```python
class GeneratedImageDocument(BaseModel):
    id: str                          # UUID
    user_id: str
    blob_id: str | None = None       # reference into BlobStore (full image); None for moderated stubs
    thumb_blob_id: str | None = None # reference into BlobStore (256 px JPG); None for moderated stubs
    prompt: str
    model_id: str                    # e.g., "grok-imagine-pro"
    group_id: str                    # e.g., "xai_imagine"
    connection_id: str
    config_snapshot: dict            # the validated config used for this generation
    width: int | None = None         # None for moderated stubs
    height: int | None = None        # None for moderated stubs
    content_type: str | None = None  # "image/jpeg" or "image/png" for real blobs; None for moderated stubs
    moderated: bool = False          # if True, this is a stub for a refused image (no blobs)
    moderation_reason: str | None = None
    tags: list[str] = Field(default_factory=list)  # placeholder for E2EE-era; unused in Phase I
    generated_at: datetime
```

**Indexes (idempotent on startup):**
- `(user_id, generated_at desc)` — gallery list
- `(user_id, id)` — individual fetch with ownership check

**Notes:**
- `moderated=True` rows are stored so partial-batch results retain a
  consistent count for audit/debug, but the inline render and gallery
  filter them out by default.
- `config_snapshot` is the exact config that produced the image; this is
  what the gallery lightbox shows ("regenerated from prompt X with these
  settings"). Future gallery features ("regenerate") rely on it.

### 4.2 `user_image_configs` collection

```python
class UserImageConfigDocument(BaseModel):
    id: str                          # composite: f"{user_id}:{connection_id}:{group_id}"
    user_id: str
    connection_id: str
    group_id: str
    config: dict                     # opaque; validated against the group's Pydantic schema on write
    selected: bool = False           # whether this is the active config for this user
    updated_at: datetime
```

**Indexes:**
- `(user_id, selected)` partial on `selected: true` — quickly find the
  active config (at most one per user)

**"Defaults over delete" behaviour:** writing a config upserts; the
"selected" flag is moved by setting the new one to `true` and clearing
the previous one in a transaction. No "deleted" event — the previous
config is kept for next-time return-to-it.

### 4.3 Shared DTOs

`shared/dtos/images.py`:

```python
# --- per-group typed configs (discriminated union) ---

class XaiImagineConfig(BaseModel):
    group_id: Literal["xai_imagine"] = "xai_imagine"
    tier: Literal["normal", "pro"] = "normal"
    resolution: Literal["1k", "2k"] = "1k"
    aspect: Literal["1:1", "16:9", "9:16", "4:3", "3:4"] = "1:1"
    n: int = Field(4, ge=1, le=10)

# Future groups append here.

ImageGroupConfig = Annotated[
    XaiImagineConfig,  # | SeedreamConfig | ...
    Field(discriminator="group_id"),
]

# --- generation results ---

class GeneratedImageResult(BaseModel):
    kind: Literal["image"] = "image"
    id: str
    width: int
    height: int
    model_id: str
    description: str | None = None   # Phase II hook (vision-derived caption)

class ModeratedRejection(BaseModel):
    kind: Literal["moderated"] = "moderated"
    reason: str | None = None

ImageGenItem = Annotated[
    GeneratedImageResult | ModeratedRejection,
    Field(discriminator="kind"),
]

# --- message references (rendered inline under assistant message) ---

class ImageRefDto(BaseModel):
    id: str                          # UUID of the generated_images row
    blob_url: str                    # /api/images/{id}/blob
    thumb_url: str                   # /api/images/{id}/thumb
    width: int
    height: int
    prompt: str
    model_id: str
    tool_call_id: str                # which tool call produced this image

# --- gallery list / detail (REST DTOs for /api/images) ---

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
```

### 4.4 ToolCallRefDto extension

`shared/dtos/chat.py` — `ToolCallRefDto` gets one new optional field:

```python
class ToolCallRefDto(BaseModel):
    # ... existing fields ...
    moderated_count: int = 0         # number of images filtered by upstream moderation
```

Default `0` ensures backwards-compatible reads of existing documents per
the migration policy in CLAUDE.md.

### 4.5 ChatMessageDto extension

`shared/dtos/chat.py` — `ChatMessageDto` gains:

```python
class ChatMessageDto(BaseModel):
    # ... existing fields ...
    image_refs: list[ImageRefDto] = Field(default_factory=list)
```

Default empty list ensures existing messages deserialise unchanged.

---

## 5. Backend API surface

### 5.1 LlmService extensions (`modules/llm/__init__.py`)

```python
async def list_image_groups(
    self, *, user_id: str
) -> list[ConnectionImageGroupsDto]:
    """For each of this user's connections that supports image generation,
    return its connection_id, display_name and the image group ids
    available for that connection."""

async def validate_image_config(
    self, *, group_id: str, config: dict
) -> ImageGroupConfig:
    """Parse and validate a raw config dict against the group's typed schema.
    Raises ValueError on mismatch."""

async def generate_images(
    self,
    *,
    user_id: str,
    connection_id: str,
    group_id: str,
    config: ImageGroupConfig,
    prompt: str,
) -> list[ImageGenItem]:
    """Resolve the connection (with ownership check), instantiate the
    adapter, call adapter.generate_images. Returns the raw item list;
    persistence is the caller's concern."""
```

### 5.2 ImageService (`modules/images/__init__.py`)

```python
class ImageService:
    async def generate_for_chat(
        self,
        *,
        user_id: str,
        prompt: str,
        tool_call_id: str,
    ) -> ImageGenerationOutcome:
        """Read the user's selected image config, call LlmService,
        persist resulting blobs + thumbnails + documents, return
        an outcome that the tool executor turns into:
          - the LLM-facing text result
          - the image_refs to attach to the assistant message
          - the moderated_count for the tool call"""

    async def list_user_images(
        self, *, user_id: str, limit: int = 50, before: datetime | None = None
    ) -> list[GeneratedImageSummaryDto]: ...

    async def get_image(
        self, *, user_id: str, image_id: str
    ) -> GeneratedImageDetailDto: ...

    async def delete_image(
        self, *, user_id: str, image_id: str
    ) -> None:
        """Delete document + blob + thumbnail. Removes references from
        any messages? No — message attachment_ids stay (broken refs
        render as "deleted image" placeholder). Phase I keeps it simple."""

    async def stream_blob(
        self, *, user_id: str, image_id: str, kind: Literal["full", "thumb"]
    ) -> tuple[bytes | AsyncIterator[bytes], str]:
        """Returns content bytes (or streaming iterator) plus content_type.
        Used by /api/images/{id}/blob and /thumb endpoints."""

    async def get_active_config(
        self, *, user_id: str
    ) -> UserImageConfigDto | None: ...

    async def set_active_config(
        self, *, user_id: str, connection_id: str, group_id: str, config: dict
    ) -> UserImageConfigDto:
        """Validate via LlmService.validate_image_config, upsert, mark as
        selected, clear previous selected in the same transaction."""
```

### 5.3 HTTP routes (`modules/images/_http.py`)

```
GET    /api/images                          → list user's generated images (paginated)
GET    /api/images/{id}                     → detail
GET    /api/images/{id}/blob                → full image stream (auth: session)
GET    /api/images/{id}/thumb               → thumbnail stream (auth: session)
DELETE /api/images/{id}                     → delete

GET    /api/images/config                   → list available connections + groups + active config
POST   /api/images/config                   → set active config (connection_id, group_id, config)
```

### 5.4 xAI adapter sub-router endpoint

The existing sub-router pattern (`/api/llm/connections/{id}/adapter/...`)
gets one new endpoint specific to xAI:

```
POST /api/llm/connections/{id}/adapter/imagine/test
     body: { group_id, config, prompt }
     → returns ImageGenItem[] without persisting (test/preview)
```

Used by the Image-Config-Panel's "Test image" button. Resolution and
auth are handled by the LLM module's existing generic resolver
dependency — the route handler only needs to validate the group_id and
config, then call adapter.generate_images directly.

---

## 6. Tool integration

### 6.1 Registration

`modules/tools/_registry.py` `_build_groups()` adds:

```python
ToolGroup(
    id="image_generation",
    display_name="Image Generation",
    description="Generate images from text prompts.",
    side="server",
    toggleable=False,    # NOT toggleable on its own — covered by tools_enabled
    tool_names=["generate_image"],
    definitions=[<JSON schema for generate_image>],
    executor=ImageGenerationToolExecutor(image_service=image_service),
)
```

The group is registered conditionally: only added if the user has at
least one connection whose adapter declares `supports_image_generation`
**and** has an active image config selected. This avoids exposing a tool
the user cannot actually run.

### 6.2 Tool signature exposed to the LLM

```json
{
  "name": "generate_image",
  "description": "Generate one or more images from a text prompt. The user has pre-configured the model, count, and image dimensions; you only choose the prompt. Be descriptive — a good prompt has subject, style, lighting, and composition cues.",
  "parameters": {
    "type": "object",
    "properties": {
      "prompt": { "type": "string", "description": "The image description." }
    },
    "required": ["prompt"]
  }
}
```

The LLM does **not** see model, count or dimensions. These come from the
user's active image config at execution time.

### 6.3 Tool-result text returned to the LLM

For a successful batch with N images and M moderated (M may be 0):

```
Generated {N-M} of {N} requested images. {M} were filtered by content moderation.

Images:
1. id=img_abc12345 (1024x1024, grok-imagine)
2. id=img_def67890 (1024x1024, grok-imagine)
3. id=img_ghi11223 (1024x1024, grok-imagine)
{...}

Use the id values to reference these images in subsequent tool calls.
```

The "use the id values" line is the Phase II hook: when ITI is added,
the model already has UUIDs in its context and a hint that they are
referenceable.

For an all-moderated batch (M == N): the tool call is recorded as
`success=false` with `error_code=image_gen.content_policy` (see §8).

### 6.4 Per-call parameter resolution

When the LLM calls `generate_image(prompt="...")`:

1. `ImageGenerationToolExecutor.execute()` calls
   `ImageService.generate_for_chat(user_id=..., prompt=..., tool_call_id=...)`.
2. `ImageService` reads the user's active `UserImageConfigDocument`.
3. Validates the stored `config` dict against the group's Pydantic schema
   (defensive — schema may have evolved since last save).
4. Calls `LlmService.generate_images(...)` with the validated typed config.
5. For each `GeneratedImageResult`: download bytes, store full + thumb in
   BlobStore, insert `GeneratedImageDocument`.
6. For each `ModeratedRejection`: insert a `GeneratedImageDocument` with
   `moderated=True` (no blobs), increment `moderated_count`.
7. Build `ImageRefDto[]` for non-moderated only, return outcome.
8. Executor formats LLM-facing text (§6.3) and signals back to the
   chat orchestrator: the assistant message persists with `image_refs`
   populated and `tool_calls[*].moderated_count` set.

If the user has no active config: tool isn't registered, can't be called.
Defence in depth: if it somehow is called, return
`error_code=image_gen.no_connection`.

---

## 7. Frontend surface

### 7.1 Cockpit Image button

**Desktop (`CockpitBar.tsx` order):** Attach, Browse, ThinkingButton,
ToolsButton, **ImageButton, separator,** IntegrationsButton, Voice, Live.

**Mobile:** the existing tools/integrations group becomes a three-button
group: Tools, **Image**, Integrations.

The button shows:
- Icon + small badge with the active model name (e.g., `imagine-pro`),
  truncated if needed.
- Inactive state if no connection supports image gen → button is greyed,
  tooltip: "No image-capable connection configured."

Clicking opens the `ImageConfigPanel` popover.

### 7.2 ImageConfigPanel

Layout, top to bottom:

1. **Connection dropdown** (image-capable connections only). If only
   one, render as a non-interactive label.
2. **Group dropdown** (image groups available on the selected
   connection). If only one, render as a non-interactive label.
3. **Group view component** loaded from the registry by `group_id`.
4. **"Test image" button** — calls the adapter test endpoint with the
   current config and a placeholder prompt ("a serene mountain
   landscape at dawn") and shows a small preview row of returned
   thumbnails. Useful to confirm the connection works before relying
   on it mid-conversation.

State changes are saved on commit (apply button) rather than per-keystroke,
to avoid spamming the backend. The "selected" flag moves atomically.

### 7.3 XaiImagineConfigView

```
┌─────────────────────────────────────────┐
│  Quality        [Normal] [ Pro  ]       │
│  Resolution     [ 1K  ] [  2K  ]        │
│  Aspect         [1:1][16:9][9:16][4:3][3:4] │
│  Count          ◀── [ 4 ] ──▶  (1–10)    │
└─────────────────────────────────────────┘
```

All controls are segmented buttons except `Count`, which is a small
stepper. No slider — segmented buttons match the discrete nature of
the underlying API.

### 7.4 Inline render under assistant messages

`InlineImageBlock` renders `message.image_refs`, optionally followed by
the small `moderated_count` notice.

**Layout rules:**
- 1 image: full width up to a max (e.g., 512 px), aspect-preserved
- 2–4 images: horizontal row, equal width
- 5–10 images: 2-column grid, equal width
- Click any image → `ImageLightbox` (full-size, with download)

If `moderated_count > 0`: small grey pill below the images, e.g.,
"1 image filtered by content moderation".

### 7.5 Gallery

Reachable from the user menu (or wherever feels natural in the existing
nav — confirm with Chris during implementation).

- Scrollable chronological grid (newest first), 4 columns desktop / 2
  mobile, infinite-scroll pagination.
- Each tile shows the thumbnail and a hover overlay with prompt snippet
  + delete button.
- Click → `GalleryLightbox` with full image, full prompt, generation
  metadata, download button, delete button.
- No search, no filters, no tags UI in Phase I.

### 7.6 Attachment picker integration

The existing attachment picker grows a tab strip:

```
[ Uploads ] [ Generated Images ]
```

`Generated Images` tab uses the same gallery component (tile grid,
chronological). Selecting one or more pushes their UUIDs into
`message.attachment_ids`, exactly like uploaded files. No copy, no
re-upload — same UUID space (`generated_images.id` is valid as an
attachment id, resolved by the backend's attachment loader).

**Implementation note:** the backend attachment loader needs to be
extended to recognise `generated_images.id` as a valid attachment
target and serve the blob from there. The exact integration point will
be in `modules/chat/` attachment resolution code; concrete file:line
will be confirmed during planning.

### 7.7 Group view registry

```typescript
// frontend/src/features/images/groups/registry.ts
import type { ImageGroupConfig } from '@/shared/dtos/images'
import { XaiImagineConfigView } from './XaiImagineConfigView'

type ConfigViewProps<T extends ImageGroupConfig> = {
  config: T
  onChange: (next: T) => void
}

type ConfigViewComponent =
  | React.ComponentType<ConfigViewProps<XaiImagineConfig>>
  // | React.ComponentType<ConfigViewProps<SeedreamConfig>>

export const IMAGE_GROUP_VIEWS: Record<string, ConfigViewComponent> = {
  xai_imagine: XaiImagineConfigView,
}
```

The discriminated union narrows the type inside each specific view; no
runtime casts.

---

## 8. Events & errors

### 8.1 Lifecycle events

No new topics. The image generation tool participates in the existing
lifecycle:

- `CHAT_TOOL_CALL_STARTED` — fires when the executor begins; frontend
  shows the standard tool-call pill in "running" state.
- `CHAT_TOOL_CALL_COMPLETED` — fires on completion (success or
  partial). Carries the standard tool-call payload.
- The assistant message is persisted with `image_refs[]` populated and
  `tool_calls[*].moderated_count` set; this propagates via the
  existing message-creation event(s).

The tool-call pill renders an in-flight spinner with text "Generating
images…" while waiting, then transitions to the standard completed
state. Inline images appear under the message via the assistant-message
render path.

### 8.2 Error codes

For `tool_call.success=false` and/or `ErrorEvent`:

| code | trigger | recoverable | user_message (suggestion) |
|---|---|---|---|
| `image_gen.content_policy` | all images filtered by upstream moderation | true | "All requested images were blocked by content moderation. Try rephrasing the prompt." |
| `image_gen.quota_exceeded` | upstream rate limit / quota | true | "Image generation quota reached. Please try again in a few minutes." |
| `image_gen.upstream_error` | 5xx from upstream, network error | true | "Image upstream is temporarily unavailable. Try again." |
| `image_gen.invalid_config` | stored config no longer validates | true | "Your image settings need attention." → opens Image panel. |
| `image_gen.no_connection` | active connection deleted between selection and call | false | "The selected image connection no longer exists. Please reconfigure." |
| `image_gen.no_image_capability` | adapter no longer supports image gen | false | "The selected connection no longer supports image generation." |

`recoverable=true` → frontend shows a retry button on the tool-call
pill. `recoverable=false` → permanent error state with the
user_message displayed; clicking opens the Image panel.

Per-image moderation that yields at least one successful image is **not
an error** — it's recorded via `tool_calls[*].moderated_count` and
displayed as the small grey pill.

---

## 9. Storage & lifecycle

### 9.1 Blob storage

Reuses the existing `BlobStore` (`backend/modules/storage/_blob_store.py`).
Two blobs per image:

- Full: original bytes from xAI (typically JPEG; preserve as returned)
- Thumb: 256 px long edge, JPEG quality ~80, generated server-side via
  Pillow

Both blobs get UUID names in the BlobStore; their ids are stored in
`GeneratedImageDocument.blob_id` and `thumb_blob_id`.

### 9.2 Thumbnail generation

In `modules/images/_thumbnails.py`:

```python
def generate_thumbnail_jpeg(image_bytes: bytes, *, max_edge: int = 256) -> bytes:
    """Resize keeping aspect ratio so the longer edge is max_edge.
    Encode as JPEG quality 80. Strip metadata (EXIF, ICC)."""
```

Generation happens synchronously on the request path. For 256 px
thumbnails of source images up to ~2K, this is sub-100ms — acceptable
without a queue. If profiling shows otherwise, move into a worker task
(scope outside Phase I).

**New dependency:** `Pillow` (`pillow>=11.0`) — added to **both**
`pyproject.toml` (root) and `backend/pyproject.toml`, per CLAUDE.md.

### 9.3 Lifetime

- Generated images are persistent and independent of chat sessions.
- Deleting a chat does **not** delete its generated images.
- Deleting an image (via gallery or lightbox) deletes the document and
  both blobs. Message references that point to the now-missing image
  render as a small "image deleted" placeholder. Phase I does not
  walk and fix-up references.
- No automatic cleanup, no quota enforcement, no TTL in Phase I.

---

## 10. Phase II hooks

The following are designed for now so Phase II adds rather than refactors:

- **UUIDs in tool result text** — the LLM has them in its context and
  is told they are referenceable. Phase II `edit_image` tool just adds
  a `source_image_id: str` parameter; no backend wiring changes needed
  beyond the new tool itself.
- **`description: str | None`** on `GeneratedImageResult` — when ITI
  iteration arrives ("make the second image warmer"), an optional
  vision-derived caption can be attached without breaking existing
  consumers.
- **`tags: list[str]`** on `GeneratedImageDocument` — empty in Phase I,
  ready for both gallery search and the future E2EE story (tags will
  be one of the few server-visible filterable fields when blobs are
  encrypted).
- **Group registry** — adding seedream / FLUX / etc. is purely:
  - new Pydantic config in `shared/dtos/images.py` (extends the union)
  - new adapter image group entry
  - new frontend view component
  - new entry in the frontend registry
  No core changes required.

---

## 11. Manual verification

These steps run against a local stack with at least one xAI connection
configured. The tester is Chris on his usual desktop + mobile device.

### 11.1 Configuration & discovery

- [ ] With **no** image-capable connection: cockpit Image button is
      greyed; tooltip explains why.
- [ ] After adding an xAI connection: Image button becomes active
      automatically (no page reload needed if events propagate).
- [ ] Open the Image panel: connection dropdown shows the xAI
      connection, group dropdown shows `xai_imagine`.
- [ ] Change tier (Normal/Pro), resolution (1K/2K), aspect, count;
      apply; close and reopen — values are persisted.
- [ ] "Test image" button returns thumbnails for a sample prompt
      within ~10 s.

### 11.2 In-chat generation

- [ ] In a chat with `tools_enabled=true`, ask the assistant to
      "draw me a cat in a teacup". Tool-call pill appears, shows
      "Generating images…", then completes.
- [ ] N images appear inline under the assistant message, matching
      the configured count (1, 4, and 10 all tested).
- [ ] Layout: 1 image full-width, 4 images horizontal, 10 images
      2-column grid.
- [ ] Click any image → lightbox opens, download button works.
- [ ] LLM's follow-up reply correctly references the count and
      acknowledges any moderated count.

### 11.3 Moderation

- [ ] Submit a prompt that triggers xAI moderation on at least one
      image (Chris will identify a deterministic-ish test prompt).
      Verify `moderated_count > 0` is shown as a grey pill below the
      successful images.
- [ ] Submit a prompt that triggers moderation on **all** images:
      tool-call pill goes red with `image_gen.content_policy`
      message; retry button visible.

### 11.4 Errors

- [ ] Disconnect from network, generate: `image_gen.upstream_error`
      surfaces; retry after reconnect succeeds.
- [ ] Use an invalid API key (temporarily): error surfaces sensibly
      (probably `image_gen.upstream_error` with the underlying
      auth detail in logs but a generic user message).
- [ ] Delete the active image connection from another tab/session;
      attempt to generate: `image_gen.no_connection` permanent error
      with link to Image panel.

### 11.5 Gallery & attachment reuse

- [ ] Open the gallery: all generated images appear chronologically;
      grid renders smoothly with thumbnails.
- [ ] Click a tile → lightbox; download and delete buttons work.
- [ ] Delete an image: it disappears from gallery; reload confirms
      persistence; an inline reference in an old chat now shows the
      "image deleted" placeholder.
- [ ] In a chat compose box, open attachment picker → "Generated
      Images" tab → select one → it appears as an attachment chip;
      send the message; assistant sees it as a normal attachment.

### 11.6 Mobile

- [ ] On the mobile cockpit, the third group button (Image) is
      reachable, opens the panel, all controls are touch-usable.
- [ ] Inline images in chat are tappable; lightbox is full-screen;
      download works on mobile.

---

## 12. Verified xAI API surface (2026-04-26 live probe)

Verified against the live xAI API with Chris's test key on the
implementation branch. These supersede the placeholders used earlier
in the spec.

- **Endpoint:** `POST https://api.x.ai/v1/images/generations`
- **Model IDs:**
  - normal tier → `grok-imagine-image`
  - pro tier → `grok-imagine-image-pro`
  - (`grok-imagine-video` also exists; out of Phase I scope)
- **Request body fields used:** `model`, `prompt`, `n` (1..10),
  `response_format` (`"url"` — we use URL because images are
  temporary and we download them immediately anyway),
  `aspect_ratio` (string), `resolution` (`"1k"` or `"2k"`).
- **Available aspect ratios:** the API accepts 14+ values
  (`1:1`, `16:9`, `9:16`, `4:3`, `3:4`, `3:2`, `2:3`, `2:1`, `1:2`,
  `19.5:9`, `9:19.5`, `20:9`, `9:20`, `auto`). **Phase I exposes
  the five common ones** (`1:1`, `16:9`, `9:16`, `4:3`, `3:4`) to
  keep the UI clean; the exotic ratios can be added later if testers
  ask.
- **Successful response item shape:**
  `{ "url": "...", "mime_type": "image/jpeg", "revised_prompt": "..." }`
  — note `revised_prompt` is xAI's rewritten version of the prompt
  (often empty); we capture it as a Phase-II hook for the Phase-II
  `description` field on `GeneratedImageResult`.
- **No `width`/`height` in the response** — we probe dimensions via
  Pillow on the downloaded bytes.
- **URL lifetime:** Cloudflare-served temp URL with a short TTL.
  The adapter MUST download immediately; storing only the URL is
  not viable.
- **Moderation:** documented as a per-item `respect_moderation`
  Boolean. On a successful test the field was absent; we therefore
  treat absence-or-True as success and only `False` as moderated.
- **Cost:** the response `usage.cost_in_usd_ticks` reports cost
  per request (1 tick = 1e-10 USD). For logging/debugging only in
  Phase I; cost UI is out of scope.

## 13. Remaining decisions for implementation time

1. **Gallery reachability** — exact entry point in the existing nav
   (user menu? sidebar item?) to be agreed during planning.
2. **Attachment loader integration point** — concrete file:line in
   `modules/chat/` for the change that lets `generated_images.id`
   resolve as a valid attachment id.

---

## 14. Summary

This is a focused Phase I that delivers TTI as a first-class chat
capability through the existing tool pipeline, with clean module
boundaries, typed per-group configurations, and explicit hooks for the
Phase II ITI work. No new event topics. One new module. One new
adapter capability. Per the Pareto principle, it covers the dominant
"draw me X" use case end-to-end and defers the harder edit/iteration
problem to a separate design pass once we have real-user feedback.
