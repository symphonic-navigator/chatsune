# Nano-GPT Image Models — Design Specification

**Date:** 2026-05-17
**Status:** Approved (pre-implementation)
**Scope:** Make the existing nano-gpt Premium Provider TTI-capable. Surface three new image models — Z-Image-Turbo, Z-Image-Base, Seedream 4.5 — via two new image groups. Refactor the TTI buffer mechanism so the second image-capable adapter can be added cleanly.
**Source brief:** In-session brainstorm with Chris on 2026-05-17. Test key available at `.nano-test-key` (gitignored, ~35 USD budget). Reference API doc: <https://docs.nano-gpt.com/api-reference/endpoint/image-generation-openai>.

---

## 1. Goal in one paragraph

Today only xAI's `xai_imagine` group can generate images. Nano-gpt already exists as a Premium Provider for chat completions; we now flip its `supports_image_generation` flag, expose two image groups (`nano_gpt_zimage` for the Z-Image family, `nano_gpt_seedream` for Seedream 4.5), and let users pick their image provider from the existing Connection dropdown that the TTI panel already supports. As a side effect we lift the byte-handoff from the adapter to the service out of a single hard-wired module import into a clean `GeneratedImageResult.data` field — making any future image provider a 30-minute addition instead of an architectural debate.

---

## 2. Non-goals

- **No xAI behaviour change.** xAI-Imagine UI, defaults, persisted configs, and event flow remain bit-identical.
- **No new gallery, no new persistence schema.** `GeneratedImageDocument`, the BlobStore, and the `/api/images/*` REST surface stay as they are.
- **No image-to-image, no editing, no inpainting.** Phase II hooks (`description` on `GeneratedImageResult`) remain unfilled.
- **No automatic provider/model defaulting.** If the user's previously-active config was `xai_imagine`, it stays selected after deploy. Switching to nano-gpt is a deliberate user action through the existing dropdown.
- **No nano-gpt admin/shared key path.** All nano-gpt calls go through the user's existing Premium Provider account (BYOK), exactly like today's chat flow.

---

## 3. Architectural changes — three layers

### 3.1 Byte-handoff refactor (cross-cutting)

The hardest constraint right now is that `ImageService` imports `drain_image_buffer` directly from `_xai_http.py` and reads a module-level dict (`_LAST_BATCH_BUFFERS`). This is the only place in the codebase coupling the generic image pipeline to a specific adapter. Two image providers cannot share this without the service growing a per-adapter import switch — which is exactly the trap we want to avoid.

**Resolution:**

- Add two fields to `GeneratedImageResult` (`shared/dtos/images.py`):
  - `data: bytes | None = None`
  - `content_type: str | None = None`
- Both fields are flagged with `Field(exclude=True)` so they never leak through Pydantic's `model_dump()` / JSON serialisation. They exist purely for the in-process handoff from adapter to `ImageService`.
- xAI adapter: replace `_LAST_BATCH_BUFFERS[image_id] = (blob_resp.content, content_type)` with assignment onto the result DTO. Delete `_LAST_BATCH_BUFFERS` and `drain_image_buffer`.
- Nano-gpt adapter: populate the same two fields.
- `ImageService.generate_for_chat`: replace `buf = drain_image_buffer(item.id); if buf is None: …` with `if item.data is None or item.content_type is None: …`. Treat missing data the same way the old code treated an empty drain (moderated-with-no-bytes stub).

The "no module-level buffer" rule applies to every future image adapter. The `BaseAdapter` docstring gets a one-line note: *image adapters return bytes inline on the result DTO; no globals.*

### 3.2 Nano-gpt adapter — image surface

`_nano_gpt_http.py` flips `supports_image_generation: ClassVar[bool] = True` and grows two methods:

```python
async def image_groups(self, connection: ResolvedConnection) -> list[str]:
    return ["nano_gpt_zimage", "nano_gpt_seedream"]

async def generate_images(
    self, connection, group_id, config, prompt,
) -> list[ImageGenItem]:
    # Dispatch on group_id, build OpenAI-shaped /images/generations request,
    # await response, fetch each URL, attach bytes + content_type to result.
```

Both groups POST to `${base_url}/images/generations` with an OpenAI-shaped body. The adapter dispatches by `group_id` to a small helper module:

- `_nano_gpt_image_groups.py`
  - `ZIMAGE_GROUP_ID = "nano_gpt_zimage"`, `SEEDREAM_GROUP_ID = "nano_gpt_seedream"`
  - `zimage_payload(config: ZImageConfig, prompt: str) -> dict`
  - `seedream_payload(config: SeedreamConfig, prompt: str) -> dict`
  - `seedream_resolution(aspect: str, quality: str) -> tuple[int, int]` — the deterministic table (§5.2)

The adapter also exposes an `/imagine/test` sub-route mirroring xAI's (used by the TTI panel's "Test image" button). Identical request/response shape — `_ImagineTestRequest` is already a generic DTO, no schema work needed.

### 3.3 Two new typed configs in `shared/dtos/images.py`

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

class SeedreamConfig(BaseModel):
    group_id: Literal["nano_gpt_seedream"] = "nano_gpt_seedream"
    aspect: Literal[
        "1:1", "16:9", "9:16",
        "4:3", "3:4",
        "3:2", "2:3",
    ] = "1:1"
    quality: Literal["standard", "high", "ultra"] = "standard"
    n: int = Field(1, ge=1, le=4)  # Seedream is expensive, cap lower.

ImageGroupConfig = Annotated[
    XaiImagineConfig | ZImageConfig | SeedreamConfig,
    Field(discriminator="group_id"),
]
```

Existing persisted `XaiImagineConfig` documents keep validating — discriminated unions are open by `group_id`. No migration script.

---

## 4. Z-Image group — UI + API mapping

### 4.1 Config view (`frontend/src/features/images/groups/ZImageConfigView.tsx`)

```
Model     [ Turbo ][ Base ]            ← SegRow, two options
Size      [ 1024 x 1024  ⌄ ]           ← native <select> with all 9 entries
Count     [ − ]  4  [ + ]              ← Stepper, 1..10
```

The size dropdown lists all nine literal strings from the type. Native `<select>` with the `OPTION_STYLE` workaround from CLAUDE.md (otherwise the open list renders in OS-light theme). No "aspect → size" indirection — what the user picks is what hits the API.

### 4.2 Request body

```json
{
  "model": "z-image-turbo" | "z-image-base",
  "prompt": "<user prompt>",
  "n": <1-10>,
  "size": "<size literal>",
  "response_format": "url"
}
```

Model slug derives from `config.model`: `f"z-image-{config.model}"`. We follow xAI's pattern of preferring `response_format: "url"` so the adapter pulls bytes in a second request — that lets us reuse the moderation/fetch-failure handling already in place for xAI.

### 4.3 Why model is in the config, not split into two groups

Z-Image-Turbo and Z-Image-Base accept exactly the same parameter shape. The only user-visible difference is generation speed and quality. Putting the model switch inside the group keeps the dropdown ladder simple: pick a connection → pick a group (Z-Image vs Seedream) → pick model + size. Splitting them into separate groups would force a redundant fourth click.

---

## 5. Seedream group — UI + API mapping

### 5.1 Config view (`frontend/src/features/images/groups/SeedreamConfigView.tsx`)

```
Aspect    [1:1][16:9][9:16][4:3][3:4][3:2][2:3]   ← SegRow, 7 options
Quality   [ Standard ][ High ][ Ultra ]           ← SegRow, 3 options
Count     [ − ]  1  [ + ]                         ← Stepper, 1..4
```

No width/height inputs exposed to the user. The mapping table in §5.2 derives concrete pixel dimensions deterministically — every aspect × quality cell is pre-computed, hardcoded in the helper module, and tested.

### 5.2 Aspect × Quality → (width, height)

The nano-gpt Seedream endpoint requires `width × height ≥ 3 686 400` pixels and, in our experience with image diffusion models, prefers dimensions that are multiples of 32. The following table satisfies both constraints and rounds to visually-natural numbers:

| Aspect | Standard (~3.7M) | High (~5M)   | Ultra (~7M)  |
|--------|------------------|--------------|--------------|
| 1:1    | 1920 × 1920      | 2240 × 2240  | 2656 × 2656  |
| 16:9   | 2560 × 1440      | 2976 × 1664  | 3520 × 1984  |
| 9:16   | 1440 × 2560      | 1664 × 2976  | 1984 × 3520  |
| 4:3    | 2240 × 1664      | 2592 × 1952  | 3072 × 2304  |
| 3:4    | 1664 × 2240      | 1952 × 2592  | 2304 × 3072  |
| 3:2    | 2368 × 1568      | 2752 × 1824  | 3264 × 2176  |
| 2:3    | 1568 × 2368      | 1824 × 2752  | 2176 × 3264  |

Implemented as a static `dict[tuple[str, str], tuple[int, int]]` in `_nano_gpt_image_groups.py`. A unit test asserts that **every cell** in the table produces ≥ 3 686 400 pixels and that both dimensions are multiples of 32. If we ever want to expose "Custom" later, that's a new field — table doesn't move.

### 5.3 Request body

```json
{
  "model": "seedream-v4.5",
  "prompt": "<user prompt>",
  "n": <1-4>,
  "width": <int>,
  "height": <int>,
  "response_format": "url"
}
```

If the nano-gpt API turns out to want `size: "WxH"` instead of separate width/height (the OpenAI convention), the adapter switches that one line. The Spike step in the implementation plan verifies which shape the live API accepts.

### 5.4 Why a count cap of 4 (vs xAI/Z-Image's 10)

Seedream at Standard quality is ~3.7M pixels per image; at Ultra it's ~7M. A request of `n=10` at Ultra is ~70M pixels — that's both slow and expensive. A cap of 4 matches the existing Grok-Imagine default and stays well under the budget where the test key ($35) would burn through during exploration. Cap is enforced by the Pydantic Field, not the UI alone.

---

## 6. Frontend registry + cockpit

### 6.1 Registry (`frontend/src/features/images/groups/registry.ts`)

```ts
export const IMAGE_GROUP_VIEWS: Partial<Record<string, ConfigViewComponent>> = {
  xai_imagine: XaiImagineConfigView as ConfigViewComponent,
  nano_gpt_zimage: ZImageConfigView as ConfigViewComponent,
  nano_gpt_seedream: SeedreamConfigView as ConfigViewComponent,
}
```

### 6.2 Defaults (`ImageConfigPanel.tsx`)

`defaultConfigForGroup` grows two branches:

```ts
function defaultConfigForGroup(groupId: string): ImageGroupConfig {
  if (groupId === 'nano_gpt_zimage') return {
    group_id: 'nano_gpt_zimage', model: 'turbo', size: '1024x1024', n: 4,
  }
  if (groupId === 'nano_gpt_seedream') return {
    group_id: 'nano_gpt_seedream', aspect: '1:1', quality: 'standard', n: 1,
  }
  if (groupId === 'xai_imagine') return { ...XAI_IMAGINE_DEFAULTS }
  return { ...XAI_IMAGINE_DEFAULTS }  // last-resort fallback
}
```

The existing connection-dropdown logic (lines 206-221) already supports >1 image-capable connection without changes — that path was the architectural prep work done during the xAI integration. The visual treatment ("Connection: <name>" label vs <select>) flips automatically based on `available.length`.

### 6.3 Empty state copy

Today: *"No image-capable connection configured. Add an xAI connection in settings."*

New: *"No image-capable connection configured. Add an xAI or nano-gpt connection in settings."*

If we add more providers later this string graduates to "Add an image-capable connection in settings." — but two providers feel concrete enough to still list both.

### 6.4 Group-label cosmetics

`groupLabel()` today just replaces underscores. That gives us:
- `xai_imagine` → "xai imagine"
- `nano_gpt_zimage` → "nano gpt zimage"
- `nano_gpt_seedream` → "nano gpt seedream"

Acceptable but ugly. We add a small static map for nicer rendering:

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

---

## 7. End-to-end flow (sanity walk)

1. User opens TTI cockpit. Backend's `list_image_groups` enumerates regular connections + Premium Provider accounts. Nano-gpt is reached via the Premium Provider branch (line 612-626 of `llm/__init__.py`), now finds `supports_image_generation=True` and returns `["nano_gpt_zimage", "nano_gpt_seedream"]`.
2. The TTI panel sees two `ConnectionImageGroupsDto` entries (xAI + nano-gpt). The connection dropdown becomes a real `<select>`.
3. User picks "nano-gpt → Z-Image → Turbo, 1024×1024, n=4". The panel auto-saves the config through the existing `/api/images/config` POST.
4. Later in a chat the LLM emits a `generate_images` tool call. `ImageService.generate_for_chat` reads the active config, calls `LlmService.generate_images`, which dispatches to the nano-gpt adapter.
5. Adapter builds the OpenAI-shaped body, POSTs to `https://nano-gpt.com/api/v1/images/generations`, fetches the URLs, attaches bytes to each `GeneratedImageResult.data`.
6. `ImageService` reads `.data` and `.content_type` directly off the DTO (no buffer drain), runs the thumbnail pipeline, persists, emits ws events — same path xAI already uses.

---

## 8. Testing strategy

### 8.1 Unit (no live API)

- **DTO validation** — round-trip ZImage and Seedream configs through `validate_image_config`. Cover legacy `XaiImagineConfig` to confirm the discriminator still routes correctly.
- **Seedream resolution table** — assert each of the 21 cells (7 aspects × 3 qualities): W × H ≥ 3 686 400 and W % 32 == 0 and H % 32 == 0.
- **Payload builders** — `zimage_payload()` and `seedream_payload()` produce stable, byte-equivalent dicts for a known config.
- **Adapter contract** — `image_groups()` returns the expected two IDs; `generate_images()` raises `ValueError` on unknown `group_id` (mirrors xAI's assertion at line 653).

### 8.2 Adapter test against live API

Behind an env-gated test (the existing `.nano-test-key` pattern), call each of the three models once with a benign prompt. Verify:
- Successful path: bytes received, dimensions probed, MIME-type passed through.
- Cost field surfaced in logs (analogous to xAI's `cost_in_usd_ticks`).

Implementation plan will spell out the exact Spike step that runs this against the live key before we commit the payload-shape decision in §5.3.

### 8.3 Manual UI verification

- Add a nano-gpt connection (already-supported flow).
- Open TTI cockpit, verify dropdown lists xAI + nano-gpt.
- Switch to nano-gpt, verify two groups appear; each loads its own config view.
- "Test image" button for each group returns thumbnails.
- Generate an image in a real chat; gallery shows the result with correct dimensions.

---

## 9. Migration & compatibility

- **No DB migration.** New configs are additive; persisted `xai_imagine` documents pass the discriminated-union validator unchanged.
- **No frontend migration.** Old localStorage / persisted UI state for the TTI panel is rehydrated through the same `applyConfig` path, which now accepts three discriminators instead of one.
- **xAI adapter contract change is forward-compatible.** `GeneratedImageResult` gains optional fields; old callers ignore them. Inside the service, the old `drain_image_buffer` flow is replaced atomically — there's no two-phase migration. Existing tests of `_xai_http` that patched `_LAST_BATCH_BUFFERS` need updating (estimated 1-2 files).

---

## 10. Build sequence (handed off to writing-plans)

A rough order, refined into a plan in the next step:

1. **Buffer refactor** — `GeneratedImageResult.data` + `.content_type`; xAI adapter, ImageService, tests.
2. **Shared DTO** — `ZImageConfig`, `SeedreamConfig`, union extension.
3. **Adapter helpers** — `_nano_gpt_image_groups.py` with payload builders and the resolution table; pure functions with unit tests.
4. **Adapter wiring** — `supports_image_generation=True`, `image_groups`, `generate_images`, `/imagine/test` sub-route on `_nano_gpt_http.py`.
5. **Spike** — adapter test against `.nano-test-key`; lock in §5.3 payload shape.
6. **Frontend views** — `ZImageConfigView.tsx`, `SeedreamConfigView.tsx`, registry entries, defaults, empty-state copy, label map.
7. **Manual QA pass** — three test images per group through the cockpit.

---

## 11. Open risks

- **Nano-gpt body shape for Seedream may differ** (e.g. expects `size: "WxH"` instead of separate `width`/`height`). Mitigated by the Spike step.
- **Z-Image `n=10` may be rate-limited or expensive at large sizes.** We keep the cap at 10 to mirror xAI; if cost in testing surprises us, we lower the Pydantic field's `le=…` before merging.
- **Seedream resolution table may need tuning** if the model produces poor quality at one of the picked dimensions. Table is in one file, one diff to adjust.
- **Buffer refactor touches xAI tests.** Diff size is small but every xAI image test needs a quick review; we run the full backend suite before merging.
