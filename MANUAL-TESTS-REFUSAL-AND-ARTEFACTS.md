# Manual Test Plan — Refusal Detection & Artefact Persistence

Companion checklist for the spec at
`docs/superpowers/specs/2026-04-11-refusal-detection-and-artefact-persistence-design.md`.

Use this during the beta smoke test. Tick items as you go; jot observations
in the **Notes** columns when something deviates from the expected behaviour
or when the real provider output looks interesting (especially `done_reason`
values — those go back into `_REFUSAL_REASONS` if we see new markers).

---

## Prerequisites

- [ ] Backend + frontend deployed together (same commit)
- [ ] Ollama Cloud API key configured in the test account
- [ ] At least one session exists to run prompts in
- [ ] Backend log stream open in a terminal for observing `ollama_base.done_reason` lines
- [ ] DevTools console open on the frontend for observing event flow

---

## Section A — Refusal happy path

### A.1 — Structured refusal from GPT-OSS Cloud

**Goal:** Verify that a refusal from the one provider we know emits structured markers reliably (GPT-OSS via Ollama Cloud) flows through the full stack.

**Steps:**

1. Select a GPT-OSS Cloud model in the chat session.
2. Send a prompt that you know triggers a refusal from GPT-OSS (Chris has one in hand).
3. Observe the live stream.
4. Wait for the stream to finish.
5. Hard-refresh the page.

**Expected:**

- [ ] During stream: refusal text appears in the assistant message area, and the **red crossed-circle** warning band appears below it ("The model declined this request. Click Regenerate to try again.")
- [ ] A toast appears with title **"Request declined"** and a **Regenerate** button
- [ ] Backend log shows `chat.stream.refused session=... correlation_id=... reason=<the actual done_reason value>`
- [ ] Backend log shows `ollama_base.done_reason model=... reason=<value>` (observability line — note the exact value in the Notes column below)
- [ ] After refresh: the refused message is still there with the red band, the content is still rendered
- [ ] The context filter works: if you send a fresh prompt **without** clicking Regenerate, the refused message is filtered out of the LLM context (verify indirectly — the new reply should behave as if the refused turn did not happen)

**Notes:**

- Observed `done_reason` value: _______________________
- Any unexpected behaviour: _______________________

---

### A.2 — Regenerate-after-refusal

**Goal:** Verify the Regenerate path from a refused message.

**Steps (after A.1 completes):**

1. Click **Regenerate** on the refusal toast, or on the Regenerate affordance beside the refused message.
2. Observe the new stream.

**Expected:**

- [ ] A new stream starts immediately
- [ ] The refused message is no longer in the LLM's context (because the orchestrator filters `status == "refused"` from history) — the model should not cite or acknowledge the previous refusal
- [ ] If the model succeeds this time: a new completed assistant message appears **below** the refused one (the refused message stays visible in history)
- [ ] If the model refuses again: a second refused message appears with its own red band and toast

**Notes:**

- Did regenerate succeed on the retry? _______________________
- How many regenerations did it take? _______________________

---

### A.3 — Content-less refusal (fallback text path)

**Goal:** Verify the code path that handles refusals where the provider sends no body.

This may or may not be reproducible empirically. If it is not, skip this section and rely on unit tests 7/8/21.

**Steps:**

1. Find a prompt that causes a provider to emit `done_reason="content_filter"` with an empty `message.content`. If you cannot reliably produce this, inspect the backend logs during A.1 to see whether GPT-OSS emits content before the refusal.
2. Observe the assistant message area.

**Expected:**

- [ ] The message is persisted even though content is empty (the `or status == "refused"` guard in `_inference.py`)
- [ ] The UI shows the fallback string "The model declined this request." (the shared `_REFUSAL_FALLBACK_TEXT` / `REFUSAL_FALLBACK_TEXT` constant) in the main content area
- [ ] The red band is also rendered
- [ ] After refresh: same state — fallback text visible, red band visible

**Notes:**

- Was this reproducible empirically? _______________________

---

## Section B — Artefact persistence

### B.1 — Create artefact, refresh, still visible

**Goal:** Verify the core of Schub 3 — an artefact card survives stream end and page refresh.

**Steps:**

1. Send a prompt that reliably triggers a `create_artefact` tool call. Example: "Write me a Python function that calculates fibonacci numbers and save it as an artefact."
2. Observe the live stream — the `ArtefactCard` should appear while the tool call is running.
3. Wait for the stream to finish.
4. **Do not refresh yet.** Confirm the card is still there (this was already broken before Schub 3 — this confirms that the new `streamingArtefactRefs` path works).
5. Hard-refresh the page.
6. Scroll to the assistant message.

**Expected:**

- [ ] Step 2: Card appears during the stream with title and type visible
- [ ] Step 4: Card is still visible **without** refresh, after the stream ended (this is the new behaviour)
- [ ] Step 6: Card is still visible **after** refresh, at the same position in the history (this is the other new behaviour)
- [ ] Clicking the card opens the artefact overlay (regression check — overlay must work for both live and persisted cards)
- [ ] The card shows the correct title, type, and update/create indicator

**Notes:**

- Any visual glitch during the live→persisted transition? _______________________

---

### B.2 — Update artefact, refresh, still visible

**Goal:** Verify that `update_artefact` tool calls also persist refs correctly.

**Steps:**

1. In a session where you already have a created artefact from B.1, send a prompt like "Update the fibonacci artefact to handle negative numbers."
2. Observe the live stream — an `ArtefactCard` with update indicator should appear.
3. Wait for the stream to finish.
4. Hard-refresh.

**Expected:**

- [ ] Both the original `create` card and the new `update` card are visible in the chat history, in chronological order
- [ ] After refresh: both cards are still there
- [ ] Clicking either card opens the overlay (the update card opens the current version of the artefact)
- [ ] Check backend log for the `ChatToolCallCompletedEvent` with `artefact_ref.operation="update"`

**Notes:**

- Any ordering issues? _______________________
- Both cards render as expected? _______________________

---

### B.3 — Multiple artefact operations in one turn

**Goal:** Verify append order is preserved for multiple artefact calls in a single assistant turn.

**Steps:**

1. Send a prompt that causes the model to create and then update an artefact within the same turn. Example: "Create a Python function that squares a number, then update it to also cube it." (Model behaviour varies — may need to retry.)
2. Observe the live stream.

**Expected:**

- [ ] Both operations produce `ArtefactCard`s during the stream
- [ ] After stream ends: both cards are still visible in the order create-then-update
- [ ] After refresh: same order preserved
- [ ] Backend log shows two `ChatToolCallCompletedEvent`s with `artefact_ref` populated, in the correct order

**Notes:**

- Was the model cooperative? _______________________
- Order preserved? _______________________

---

### B.4 — Artefact during an aborted stream

**Goal:** Verify the S3-b decision — artefact refs are persisted even when the stream status is `"aborted"`.

**Steps:**

1. Temporarily lower `LLM_STREAM_ABORT_SECONDS` in the backend environment to something aggressive like 10s.
2. Restart the backend with the new env value.
3. Send a prompt that creates an artefact and then continues with a long monologue (so the gutter trips mid-stream). Example: "Create an artefact with a Python function, then explain fibonacci numbers in extreme detail across ten pages."
4. Wait for the abort to trigger.
5. Observe the UI.
6. Hard-refresh.
7. **Restore `LLM_STREAM_ABORT_SECONDS`** to the production value afterwards.

**Expected:**

- [ ] The amber **aborted** warning band appears on the assistant message
- [ ] The artefact card is **still visible** despite the aborted stream (the persistence applies regardless of stream end status)
- [ ] Clicking the card opens the artefact overlay
- [ ] After refresh: both the amber band and the artefact card remain
- [ ] `LLM_STREAM_ABORT_SECONDS` restored to production value

**Notes:**

- Did the abort trip at the expected time? _______________________
- Card visible after abort and after refresh? _______________________

---

## Section C — Regression guards (Schub 1 unaffected)

These ensure the new changes did not break Schub 1 behaviour.

### C.1 — Normal completed stream still works

- [ ] Send a normal prompt, receive a normal completion
- [ ] No red band, no amber band, no toast
- [ ] Message persists correctly through refresh

### C.2 — Aborted stream (without artefact) still works

- [ ] Trigger a plain abort (lower `LLM_STREAM_ABORT_SECONDS`, send a prompt, let it time out)
- [ ] Amber band appears
- [ ] Toast with title "Response interrupted" and Regenerate button appears
- [ ] After refresh: amber band still visible
- [ ] `LLM_STREAM_ABORT_SECONDS` restored

### C.3 — Slow-but-not-aborted stream still works

- [ ] Trigger a slow stream (send a prompt that takes > 30s but < 120s to produce first output)
- [ ] Subtle slow hint appears in the gutter
- [ ] Stream eventually completes, no abort, no red/amber band

### C.4 — Web search pills still render

- [ ] Send a prompt that triggers `web_search`
- [ ] Web search pills render during stream
- [ ] After refresh: pills still there

### C.5 — Knowledge search pills still render

- [ ] Send a prompt that triggers `knowledge_search`
- [ ] Knowledge pills render during stream
- [ ] After refresh: pills still there

---

## Section D — Schub 4.1 piggyback

### D.1 — Usage is persisted

**Goal:** Verify the opportunistic fix — `usage` is now stored on chat messages.

**Steps:**

1. Send a normal completed prompt.
2. After completion, inspect the Mongo document directly (via mongosh or a DB UI) or check the reloaded message DTO in DevTools.

**Expected:**

- [ ] The Mongo document has a `usage` field with `input_tokens` and `output_tokens` populated
- [ ] The `ChatMessageDto` after refresh contains the `usage` field
- [ ] Legacy messages (created before this deploy) still load correctly with `usage: null`

**Notes:**

- Sample values observed (input / output): _______________________

---

## Observability Summary

After the beta test window, review the backend logs and fill in:

- **Real `done_reason` values seen in production:**
  - _______________________
  - _______________________
  - _______________________
- **Any new refusal markers to add to `_REFUSAL_REASONS`:** _______________________
- **Total refusals observed during window:** _______________________
- **Any unexpected crashes or tracebacks in the refusal path:** _______________________

---

## Sign-off

- [ ] All of Section A passes
- [ ] All of Section B passes
- [ ] All of Section C passes (regression)
- [ ] Section D passes
- [ ] `LLM_STREAM_ABORT_SECONDS` is back at the production value
- [ ] Observability summary filled in

Tested by: _______________________
Date: _______________________
Build: _______________________
