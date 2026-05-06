# Project Custom Instructions — adding a project-level CI layer to the assembled system prompt

Date: 2026-05-06
Status: Draft, ready for implementation

This spec adds a per-project Custom Instructions (CI) field that becomes
a new layer in the assembled system prompt sent to the LLM. The new
layer sits between the model-instructions layer and the persona layer,
so the order on inference is: admin → model → **project** → persona →
… → about-me.

The CI is edited per project in the project overview tab. When a chat
session moves between projects, the next inference call automatically
picks up the new project's CI — at the cost of a one-time provider-cache
miss, which is accepted (the alternative would be wrong CI text on the
following turn, which is worse than a cache miss).

---

## 1. Motivation

Personas already carry a system prompt, but it is the persona's voice
and behaviour that they describe — useful, but not the right place to
encode project context (e.g. "this project is a fantasy worldbuilding
sandbox; treat invented place names as canon" or "this project is the
quarterly OKR planning workspace; default to British business English
and crisp bullet lists").

Other chat clients (ChatGPT, Claude.ai, Gemini Gems) ship the same
notion: a project / workspace owns a free-text instruction block that
is layered on top of the assistant's own persona. Chatsune's projects
are otherwise feature-complete (title, emoji, description, NSFW flag,
pinning, knowledge libraries) — adding CI is the missing piece for
project-scoped behaviour shaping.

Out of scope: Default project assignment per persona is already
modelled (`PersonaDto.default_project_id`, see `shared/dtos/persona.py`).
Cross-project inheritance, per-CI versioning, or per-CI templates are
explicitly **not** part of this spec.

---

## 2. Design summary

A new optional field `system_prompt: str | None` is added to the
project document and DTO. The chat prompt assembler reads it on every
inference call and emits a `<projectinstructions priority="high">`
layer between the model and persona layers. The frontend exposes the
field as a save-on-blur textarea in the project overview tab, parallel
to the existing `description` field.

No migration is required: the field defaults to `None` so legacy
documents deserialise unchanged. No new HTTP routes, no new event
topics — the existing `ProjectUpdatedEvent` carries the full
`ProjectDto` and propagates the new field for free.

---

## 3. Prompt-layer order

Updated layer order in `backend/modules/chat/_prompt_assembler.py`:

| Layer | Tag | Source | Trust |
|-------|-----|--------|-------|
| 1 | `<systeminstructions priority="highest">` | admin / settings | trusted, NOT sanitised |
| 2 | `<modelinstructions priority="high">` | per-user-model config | user-controlled, sanitised |
| **3** | **`<projectinstructions priority="high">`** | **project.system_prompt** | **user-controlled, sanitised** |
| 4 | `<you priority="normal">` | persona.system_prompt | user-controlled, sanitised |
| (5) | soft-CoT, memory, integrations, tool-availability | mixed | mixed |
| 6 | `<userinfo priority="low">` | user.about_me | user-controlled, sanitised |

Rationale for placement: model instructions are technical model-level
guidance (reasoning quirks, format hints) and stay close to the admin
layer. Project instructions are content-level scope ("you are working
inside the OKR planning workspace") and bracket the persona, taking
precedence over the persona's voice when they conflict — which is the
expected mental model for the user editing them.

---

## 4. Backend changes

### 4.1 Data model

`backend/modules/project/_models.py` — `ProjectDocument`:

```python
class ProjectDocument(BaseModel):
    id: str
    user_id: str
    title: str
    emoji: str | None
    description: str | None = None
    nsfw: bool
    pinned: bool
    sort_order: int = 0
    knowledge_library_ids: list[str] = Field(default_factory=list)
    system_prompt: str | None = None    # NEW
    created_at: datetime
    updated_at: datetime
```

The field defaults to `None`, which makes pre-existing MongoDB
documents deserialise without raising — the "backwards-compatible
reads are the default" rule from `CLAUDE.md` applies. No migration
script is needed.

### 4.2 DTOs

`shared/dtos/project.py`:

```python
class ProjectDto(BaseModel):
    ...existing fields...
    system_prompt: str | None = None    # NEW

class ProjectCreateDto(BaseModel):
    ...existing fields...
    system_prompt: str | None = None    # NEW (optional at create)

class ProjectUpdateDto(BaseModel):
    ...existing fields...
    system_prompt: str | None | _Unset = Field(default=UNSET)    # NEW
```

The update DTO uses the same `UNSET` sentinel as `description`,
`emoji`, and `knowledge_library_ids` so PATCH callers can distinguish
"field omitted, do not touch" from "explicit null, clear the CI" from
"explicit string, set the CI".

No length limit. Persona's `system_prompt` is already unbounded in the
DTO (see `shared/dtos/persona.py:63`); the only guardrail is the
existing 16k-character warning emitted by the assembler when the total
assembled prompt is large (`_prompt_assembler.py:156`). Consistency
with persona wins over a per-field cap.

### 4.3 Repository

`backend/modules/project/_repository.py` — new method:

```python
async def get_system_prompt(
    self, project_id: str, user_id: str
) -> str | None:
    """Projection-only fetch of a project's CI, scoped to the owner.

    Returns None if the project does not exist, is not owned by the
    user, or has no CI set.
    """
    doc = await self._coll.find_one(
        {"_id": project_id, "user_id": user_id},
        projection={"system_prompt": 1},
    )
    if doc is None:
        return None
    return doc.get("system_prompt")
```

The projection-only fetch is the same pattern as `get_library_ids`
(used per inference turn, see `_orchestrator.py:534`) — cheap enough
that no in-process cache is worth the staleness risk.

The existing repository update path that backs `PATCH /api/projects/{id}`
already iterates `ProjectUpdateDto` fields and emits a `$set` for any
non-`UNSET` value while skipping `UNSET`. The new field reuses that
mechanism unchanged.

### 4.4 Public module API

`backend/modules/project/__init__.py` — new export:

```python
async def get_system_prompt(project_id: str, user_id: str) -> str | None:
    """Return the project's CI or None.

    Returns None if the project does not exist, does not belong to the
    user, or has no CI set. Never raises — chat inference must not die
    because of a CI lookup. Errors are swallowed and logged at the
    caller side, mirroring the project-library lookup pattern in the
    orchestrator.
    """
    return await _repo().get_system_prompt(project_id, user_id)
```

Added to `__all__`.

### 4.5 Prompt assembler

`backend/modules/chat/_prompt_assembler.py`:

```python
async def _get_project_prompt(
    project_id: str | None, user_id: str
) -> str | None:
    if not project_id:
        return None
    from backend.modules import project as project_service
    return await project_service.get_system_prompt(project_id, user_id)
```

`assemble()` signature gains an optional keyword-only `project_id`:

```python
async def assemble(
    user_id: str,
    persona_id: str | None,
    model_unique_id: str,
    *,
    project_id: str | None = None,
    supports_reasoning: bool = False,
    reasoning_enabled_for_call: bool = False,
    tools_enabled: bool = False,
) -> str:
    ...
    project_prompt = await _get_project_prompt(project_id, user_id)
    ...
    # Layer 3: Project — user-controlled, sanitised
    if project_prompt and project_prompt.strip():
        cleaned = sanitise(project_prompt.strip())
        if cleaned:
            parts.append(
                f'<projectinstructions priority="high">\n'
                f'{cleaned}\n'
                f'</projectinstructions>'
            )
```

`assemble_preview()` is **not** changed. Project CI does not appear in
the persona-editor preview, consistent with the "project is optional
from the persona's perspective" decision.

### 4.6 Orchestrator wiring

`backend/modules/chat/_orchestrator.py:577` — pass the session's
project ID through:

```python
system_prompt = await assemble(
    user_id=user_id,
    persona_id=persona_id,
    model_unique_id=model_unique_id,
    project_id=session.get("project_id"),    # NEW
    supports_reasoning=supports_reasoning,
    reasoning_enabled_for_call=reasoning_enabled,
    tools_enabled=tools_enabled_flag,
)
```

Because `assemble()` runs once per inference turn, a session-level
project switch (`chat.session.project.updated` event) is automatically
reflected on the **next** send — no in-process cache, no event-bus
plumbing. The provider-side prompt cache (Anthropic ephemeral cache,
Ollama Cloud's KV cache, etc.) loses the prefix match for that turn;
the cache rebuilds on the following turns. This is an accepted cost.

### 4.7 HTTP API

No new routes. The existing endpoints carry the field through the DTO
extensions:

- `POST /api/projects` — `ProjectCreateDto` includes `system_prompt`
- `PATCH /api/projects/{id}` — `ProjectUpdateDto` includes
  `system_prompt` with the `UNSET` sentinel
- `GET /api/projects/{id}` — `ProjectDto` includes `system_prompt`
- `GET /api/projects` — list endpoint returns the field via the same
  DTO

### 4.8 Events

No new event topics. `ProjectUpdatedEvent` (`shared/events/project.py:19`)
already wraps the full `ProjectDto`, so the new field propagates
through the existing WebSocket pipe automatically.

---

## 5. Frontend changes

### 5.1 Project type

`frontend/src/features/projects/types.ts` — add `system_prompt: string
| null` to the `Project` type.

`frontend/src/features/projects/projectsApi.ts` — if the file owns a
`UpdateProjectPayload` interface, add `system_prompt?: string | null`.

### 5.2 Project overview tab

`frontend/src/features/projects/tabs/ProjectOverviewTab.tsx` — new
section between description and NSFW toggle.

Local state mirrors the existing `description` pattern
(`ProjectOverviewTab.tsx:47,65`):

```tsx
const [systemPrompt, setSystemPrompt] = useState(project?.system_prompt ?? '')
const [editingSystemPrompt, setEditingSystemPrompt] = useState(false)

useEffect(() => {
  if (!editingSystemPrompt) setSystemPrompt(project.system_prompt ?? '')
}, [project.system_prompt, editingSystemPrompt])
```

Save-on-blur handler mirrors `description`'s blur handler
(`ProjectOverviewTab.tsx:145-157`):

```tsx
const handleSystemPromptBlur = async () => {
  const trimmed = systemPrompt.trim()
  const current = project?.system_prompt ?? ''
  if (trimmed === current) {
    setEditingSystemPrompt(false)
    return
  }
  await patch({ system_prompt: trimmed === '' ? null : trimmed })
  setEditingSystemPrompt(false)
}
```

Markup with the existing visual rhythm — section heading + a single
helper sentence so the user does not confuse this with `description`:

```tsx
<section>
  <label htmlFor="project-overview-system-prompt" className="...">
    Custom Instructions
  </label>
  <p className="text-xs text-white/50 mb-1">
    Sent to the model as instructions for this project. Sits between
    model-level guidance and the persona.
  </p>
  <textarea
    id="project-overview-system-prompt"
    value={systemPrompt}
    onChange={(e) => setSystemPrompt(e.target.value)}
    onFocus={() => setEditingSystemPrompt(true)}
    onBlur={handleSystemPromptBlur}
    placeholder="Custom instructions for this project (optional)…"
    rows={6}
    data-testid="project-overview-system-prompt"
    className="..."  // same Tailwind classes as the description textarea
  />
</section>
```

### 5.3 Store and WebSocket

No changes to `useProjectsStore`. The existing
`project.updated`-event handler replaces the project in the cache,
and `system_prompt` flows through the DTO automatically.

### 5.4 Project switch in chat

No frontend work. The chat session's `project_id` change triggers the
existing `chat.session.project.updated` event; the next send on the
backend assembles the prompt with the new project's CI. The frontend
does not need to know.

---

## 6. Tests

### 6.1 Backend

`backend/modules/chat/_prompt_assembler` tests — extend the existing
assembler test module:

- With `project_id` and a project that has a CI: the assembled prompt
  contains a `<projectinstructions>` block, and that block's substring
  index is **between** the `<modelinstructions>` and `<you>` indices
  (assert order, not exact byte content).
- With `project_id` but no CI on the project: no `<projectinstructions>`
  tag in the output.
- Without `project_id`: no `<projectinstructions>` tag.
- Sanitisation runs: a CI containing `</systeminstructions>` does not
  produce a literal closing tag in the output.
- Project owned by a different user: `get_system_prompt` returns
  `None`, no layer in the output (cross-tenancy guard).

`backend/modules/project/_repository` tests:

- `get_system_prompt` returns the value for the owner.
- Returns `None` for a missing project.
- Returns `None` for a project owned by a different user.
- Returns `None` when the project exists but has no CI.

`backend/modules/project/_handlers` (or its existing CRUD test file):

- `POST /api/projects` accepts `system_prompt` and round-trips it.
- `PATCH /api/projects/{id}` with `system_prompt` set updates the
  field; with `system_prompt: null` clears it; without the field
  leaves it untouched.

### 6.2 Frontend

`frontend/src/features/projects/__tests__/ProjectOverviewTab.test.tsx`
— extend with cases for the new textarea:

- Renders the textarea with the project's current CI.
- Typing into the textarea updates local state without firing a PATCH.
- Blur with changed text fires a PATCH carrying the new
  `system_prompt`.
- Blur with empty text fires a PATCH carrying `system_prompt: null`.
- Blur with unchanged text does not fire a PATCH.

---

## 7. Migration & data hygiene

**No migration needed.** Pydantic default `None` covers legacy
documents. Compliance with the "no more wipes" rule is automatic.

**No index changes.** The CI field is not used in queries.

---

## 8. Manual verification

After implementation, Chris runs the following on real data:

1. **Empty CI baseline.** Create a fresh project with no CI. Start a
   chat in it and send a message. Inspect the backend log — the
   assembled system prompt for that turn must not contain a
   `<projectinstructions>` block.
2. **Set a CI, observe propagation.** Open the project's overview
   tab, type a CI, blur the textarea. Confirm via the WS inspector
   (or browser devtools) that a `project.updated` event arrives with
   `system_prompt` set. Confirm the backend log records the PATCH.
3. **CI takes effect on the next send.** Send another message in the
   same chat. The backend log must now show a `<projectinstructions>`
   block between `<modelinstructions>` and `<you>`.
4. **Cross-project switch.** Move the chat session to a different
   project (or detach it). Send a message. The assembled prompt must
   reflect the **new** project's CI (or no CI block at all if the
   session is detached). Provider cache hit rate is expected to drop
   for that one turn.
5. **Clear the CI.** Open the overview tab, empty the textarea, blur.
   Confirm the PATCH carries `system_prompt: null` and that the next
   send omits the `<projectinstructions>` layer.
6. **Cross-user isolation.** With two user accounts, set a CI on a
   project owned by user A. User B (who somehow learns the project
   ID) cannot read the CI through any API surface — the repository's
   `user_id`-scoped query returns `None`.
7. **Long-CI warning.** Paste a very long CI (>16k characters of
   total assembled prompt). Confirm a backend log warning fires
   ("Assembled system prompt is very large…"), but the inference
   still proceeds.

---

## 9. Open questions

None. All decisions captured during brainstorming are reflected
above.

---

## 10. Out of scope

- Default CI templates per project category.
- CI versioning / history.
- CI inheritance from a parent project (no project hierarchy exists).
- A toggle to show / hide the project layer at chat-session level.
  The session's `project_id` is the on/off switch; this is enough.
- Surfacing CI in `assemble_preview()` (explicitly excluded by the
  decision in Section 4.5).
