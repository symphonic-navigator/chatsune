# Stream Abort & Error Toasts — Follow-up Schübe

Schub 1 shipped on `caabaed` (2026-04-11). It delivered:

- Two-stage Ollama gutter state machine (slow at 30 s, abort at 120 s via `LLM_STREAM_ABORT_SECONDS`)
- `StreamSlow` / `StreamAborted` adapter events, `ChatStreamSlowEvent` topic, extended `ChatStreamEndedEvent.status` with `"aborted"`
- Persisted `status: "completed" | "aborted"` on `ChatMessageDto`, aborted messages filtered from LLM context
- Frontend amber warning band, subtle slow hint, error toasts with inline Regenerate

Design spec: `docs/superpowers/specs/2026-04-11-stream-abort-and-error-toasts-design.md`
Implementation plan: `docs/superpowers/plans/2026-04-11-stream-abort-and-error-toasts.md`

Schub 2 and Schub 3 are the deliberately-deferred follow-ups from the same brainstorming session. Both are described below in enough detail that a future session can pick them up without re-brainstorming the user intent.

---

## Schub 2 — Refusal detection and context protection

### Goal

When an LLM provider explicitly signals that it refused a request, Chatsune should:

1. Show the refusal in the chat history with a **red** warning band (reserved colour — amber is already in use for interrupted/incomplete, red is reserved for refusals).
2. Fire an error toast so the user sees it immediately.
3. **Never** inject the refusal back into the LLM context on subsequent turns — refusals are known to poison context and make future refusals more likely (the well-documented GPT-4o behaviour from mid-2024).

### Decisions already made (do not re-litigate)

- **Strict detection only.** Chatsune catches refusals only when the provider explicitly marks them. No heuristic text matching (no "I cannot", no "I'm sorry, I won't"). Reason: Chatsune has international users (DE, EN, FR, JA already in scope); language-dependent heuristics are too unreliable.
- **Consequence the user accepted**: in practice, most refusals from local models (Llama, GLM, Qwen, DeepSeek) will flow through as normal content because these models do not emit a structured refusal signal. Only OpenAI-style providers (via their `refusal` field) and Ollama's `done_reason` values like `content_filter` will be caught reliably. This is fine as a starting point.
- **Refusals are persisted in the chat history.** The user wants to see what happened. They are only filtered out at the LLM-context-build step, not at the UI-render step.
- **Red is reserved for refusals.** Amber stays the "interrupted but recoverable" colour from Schub 1. Keep the colour language consistent.

### Backend signals to look at

- Ollama NDJSON response's `done_reason` field. Known values worth handling: `"content_filter"`, `"refusal"`, whatever else shows up empirically. The LLM Test Harness (`backend/llm_harness/`) is the right tool to probe this — CLAUDE.md mandates using it before guessing.
- Ollama Cloud acts as a provider bridge. If an upstream OpenAI-compatible adapter inside Ollama Cloud forwards a structured `refusal` field, verify whether Ollama surfaces it in `done_reason` or swallows it. Test empirically.
- OpenAI API itself (not used today but possibly later) uses a dedicated `delta.refusal` stream field — a separate code path from `done_reason`. If a future adapter for OpenAI-style endpoints gets added, this is where refusal detection hooks in.

### Proposed scope (open to revision during Schub 2 brainstorming)

- New adapter event: `StreamRefused(reason: str, refusal_text: str | None)` in `backend/modules/llm/_adapters/_events.py`. Re-exported via `backend/modules/llm/__init__.py`.
- Ollama adapter parses the final `done` chunk's `done_reason` field; if it matches a known refusal signal, yield `StreamRefused(...)` in addition to (or instead of) `StreamDone`.
- Chat inference handler gains a match arm for `StreamRefused`: sets `status = "refused"`, emits a `ChatStreamErrorEvent` with `error_code = "refusal"` and `recoverable = False` (refusals are not meaningful to retry mechanically), saves the message with `status = "refused"`.
- Shared contracts:
  - `ChatStreamEndedEvent.status` gains a fifth literal `"refused"`.
  - `ChatMessageDto.status` gains a third literal `"refused"` alongside the existing `"completed" | "aborted"`.
  - Optional new field on the DTO: `refusal_text: str | None = None` to carry the provider's refusal body separately from the normal `content` field (so the UI can render it distinctly).
- Repository: `save_message` accepts the new `"refused"` status and the new `refusal_text` field. `message_to_dto` reads them back with safe defaults for legacy documents.
- Orchestrator: extend the aborted-context-filter in `run_inference` to also drop messages with `status == "refused"`. The same comprehension pattern works — just add `"refused"` to the excluded set.
- Frontend:
  - `ChatMessageDto` TypeScript interface mirrors the new status literal and `refusal_text` field.
  - `AssistantMessage` gains a `RefusalBlock` render branch (red border, red-tinted background, refusal text if present, otherwise a generic "The model declined this request" message).
  - `useChatStream` dispatches an error toast on refusal with level `error` and no Regenerate action (refusals are not recoverable — if the user wants, they can manually edit and resend).

### Open questions for Schub 2 brainstorming

- Should the Regenerate action be fully suppressed on refusal, or should we keep it as a weak affordance ("try again with different wording")? Default: suppress. User confirmed in Schub 1 brainstorming that refusals should be clearly final, not offer a retry shortcut.
- If the refusal carries no `refusal_text` from the provider (e.g. `done_reason = "content_filter"` with an empty final chunk), what do we render? Default: a fixed fallback string like "The model declined this request. Reason was not provided."
- Do we log refusals for later analysis? Worth a structured `_log.warning("chat.stream.refused ...")` at the inference layer with session, correlation, reason — consistent with Schub 1's abort logging.
- Should `recoverable = False` on the error event be overridden for the Regenerate button question above? These two decisions are the same decision under different names — decide once.

---

## Schub 3 — Artefact tool call persistence

### Goal

Right now, when a chat message includes an artefact tool call (`create_artefact` or `update_artefact`), the user sees the artefact card only during the live stream. Once the stream ends, the card disappears because the frontend clears `activeToolCalls` on `finishStreaming`. After a page refresh there is no trace of the artefact in the chat history — even though the artefact itself is safely in the database.

Schub 3 persists the artefact references on the chat message itself so the card survives the stream end and the refresh.

### Decisions already made

- **Only artefact tool calls need persistence.** `web_search` and `knowledge_search` already persist via existing `web_search_context` and `knowledge_context` fields on `ChatMessageDto`. Artefacts are the outlier — they emit `ArtefactCreatedEvent` / `ArtefactUpdatedEvent` but nothing is attached to the message that triggered them.
- **The frontend pattern already exists.** `MessageList.tsx` renders `WebSearchPills` and `KnowledgePills` from persisted message fields. The same pattern should apply to artefacts: a persisted list on the message, rendered every time the message is drawn.
- **The UI element already exists.** `ArtefactCard.tsx` is already capable of rendering from a static handle + title + type. It just needs to be fed from a persistent source instead of the ephemeral `activeToolCalls` state.

### Root cause of the Schub 1 symptom (GLM-5 calculator attempt)

During the user's GLM-5 calculator test that motivated the whole feature, the symptom was "sieht nichts und stiller Abbruch nach 90 s". The stiller-Abbruch part is fixed by Schub 1 (the gutter state machine catches it now). The sieht-nichts part is partly Schub 1 (the UI now shows the warn band on abort) and partly Schub 3 (even when the artefact is created successfully, the user only briefly sees the card during streaming and loses it after).

### Proposed scope (open to revision during Schub 3 brainstorming)

- New field on `ChatMessageDto`: `artefact_refs: list[ArtefactRef] | None = None` where `ArtefactRef` is a small DTO with `{artefact_id, handle, title, type, operation: "create" | "update"}`. Analogous to `web_search_context` but artefact-specific.
- Backend: `_inference.py`'s tool loop already captures web_search results into `web_search_context`. Add a parallel capture for `create_artefact` and `update_artefact` calls into a local `artefact_refs` list. Pass it through to `save_fn` alongside the existing kwargs.
- Repository: `save_message` accepts the new `artefact_refs` kwarg. `message_to_dto` reads it back.
- Frontend:
  - `ChatMessageDto` TypeScript interface mirrors the new field.
  - `MessageList.tsx` renders an `ArtefactCard` for each entry in `msg.artefact_refs` inside the persisted-messages map (analogous to how `WebSearchPills` and `KnowledgePills` are rendered).
  - The streaming-block rendering of `ArtefactCard` (from `activeToolCalls` with `status === 'done'`) stays for live feedback during the current turn. It is only the post-stream gap that Schub 3 closes.

### Open questions for Schub 3 brainstorming

- Field name. `artefact_refs` is descriptive and parallels `web_search_context`. Alternative: `tool_call_refs` if we want to generalise now rather than later. Default: stay narrow, call it `artefact_refs`.
- Should we capture `create_artefact` and `update_artefact` calls even on streams that ended as `"aborted"`? The artefact was successfully created even though the model's follow-up stream died. Default: yes, persist the refs regardless of stream status — the artefact exists in the DB and the user should see it.
- Ordering. If a message has multiple artefact operations (create + update in the same turn), the persisted list should preserve order so the UI renders them chronologically.
- Click-through. `ArtefactCard` already opens an overlay on click — verify the overlay works for persisted (refreshed-from-DB) cards, not just live ones.

---

## When picking up Schub 2 or Schub 3

Invoke the brainstorming skill (`superpowers:brainstorming`) at the start of the session to re-confirm scope and decisions. Reference this file so the new brainstorm can load the already-made decisions into context rather than rediscovering them. Then proceed into writing-plans → subagent-driven-development exactly like Schub 1.

The Schub 1 spec and plan are the template for how the artefacts of each schub should look.
