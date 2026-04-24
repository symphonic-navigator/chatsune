# Cockpit Toolbar Redesign

**Date:** 2026-04-24
**Status:** Approved — ready for implementation planning
**Scope:** Frontend, plus a small backend extension to the ChatSession state

## Summary

Replace the current scattered composer toolbar (Thinking button above the input, voice button below, integration emergency-stop as a separate sibling, a mobile-only wrench tray) with a single compact "cockpit" row: attachments on the left, session toggles in the middle, device/service controls on the right. All buttons are always visible; unavailable ones render disabled with an inline "activate this first" explanation.

## Motivation

The present composer has three problems:

1. **Fragmented layout.** Thinking, tools, integrations, voice and live-mode controls are spread across two rows plus a mobile-only tray. Users have to look in several places to understand the current state.
2. **No path to "reasoning-only" runs.** Some models cannot mix reasoning and tool use; the current UI offers no way to disable *all* tools (including persona-bound integration tools) so the user can observe reasoning.
3. **Mobile clutter.** The wrench-tray pattern is an extra tap layer that duplicates desktop functionality instead of mirroring it cleanly.

The cockpit collapses everything into one responsive row — informative at a glance, identical model on desktop and mobile, with disabled-state explanations taking the place of discovery menus.

## Goals

- One compact, always-visible button row above the prompt input.
- Identical mental model on desktop and mobile; only the affordance for reading panel content differs (hover vs. info modal).
- Every button has exactly one primary click action. Panels provide context and, where relevant, secondary actions.
- Session-persistent toggles for Thinking, Tools and Auto-Read, initialised from persona defaults on each new chat.
- A single "magic" voice button whose behaviour adapts to live-mode and playback state.
- A reusable `CockpitButton` primitive that also gives the codebase its first real tooltip/popover primitive.

## Non-goals / deferred

- **Backend changes beyond the ChatSession state fields described in "Backend changes" below.** LLM adapter code, integration APIs and voice APIs remain as they are.
- **Model capability detection for reasoning + tools conflict.** We currently do not know, per model, whether reasoning and tool use can coexist. For now both toggles are independently operable; no warning, no lock. This is a known unknown, revisited after the platform answers whether per-model capability metadata is maintained by us or sourced elsewhere.
- **Changing how integrations are activated for a persona.** Activation continues to live in the persona editor; the cockpit only surfaces active state and the emergency stop.

## Layout

Order (left to right, always visible):

| Group | Desktop (≥ 1024 px) | Mobile (< 1024 px) |
|-------|---------------------|--------------------|
| Attachments | `Attach` · `Browse` | `Attach` · `Camera` · `Browse` |
| *separator* | | |
| Session toggles | `Thinking` · `Tools` | `Thinking` · `Tools` |
| *separator* | | |
| Service controls | `Integrations` | `Integrations` |
| *separator* | | |
| Voice (magic button) | `Voice` | `Voice` |
| *separator* | | |
| Live | `Live` | `Live` |
| *separator* | — | `Info` |

The row wraps horizontally on narrow viewports; no inline scroll. Camera is mobile-only; on desktop, file input via Attach covers the same territory. Info is mobile-only and opens the info modal (see "Mobile" below).

## Component architecture

New directory: `frontend/src/features/chat/cockpit/`.

```
cockpit/
  CockpitBar.tsx            — container, responsive ordering, separators
  CockpitButton.tsx         — primitive: icon, state colour, disabled, hover panel slot, title tooltip
  cockpitStore.ts           — session-scoped toggle state (thinking, tools, autoRead)
  MobileInfoModal.tsx       — bottom-sheet accordion rendering the same panel contracts
  buttons/
    AttachButton.tsx        — delegates to existing file-input handling
    CameraButton.tsx        — mobile-only; delegates to existing camera flow
    BrowseButton.tsx        — delegates to existing uploads browser
    ThinkingButton.tsx      — toggle; hover panel with description + current state
    ToolsButton.tsx         — toggle; hover panel with active tool groups (read-only)
    IntegrationsButton.tsx  — click-popover with per-integration stop + emergency stop
    VoiceButton.tsx         — magic button; state machine defined below
    LiveButton.tsx          — toggle; hover panel with description
```

`CockpitButton` is the shared primitive. It renders:

- An icon slot (emoji or SVG).
- A state colour (idle / active / playback / muted / disabled).
- A native `title` tooltip for Attach/Camera/Browse.
- An optional hover panel slot; the panel is sticky-on-hover (pointer-enter into the panel keeps it open, pointer-leave closes it) so interactive controls inside the panel remain usable.
- A disabled state whose panel slot shows the "activate this first" message.

Each button component is a thin adapter that reads the right store(s), composes the panel content, and passes it to `CockpitButton`. No button component owns its own ad-hoc tooltip or popover implementation.

## State model

The authoritative state for the three session toggles lives on the **ChatSession document in the backend**. The frontend `cockpitStore` is a thin cache that mirrors those three fields for the currently open chat and writes through to the existing session-update API on toggle.

`cockpitStore` (Zustand) holds, **per `sessionId`**:

```ts
type CockpitSessionState = {
  thinking: boolean     // mirrors ChatSession.reasoning_override
  tools: boolean        // mirrors ChatSession.tools_enabled
  autoRead: boolean     // mirrors ChatSession.auto_read
}
type CockpitStore = {
  bySession: Record<string, CockpitSessionState>
  hydrateFromServer(sessionId: string, state: CockpitSessionState): void
  setThinking(sessionId: string, value: boolean): void  // writes to server, then updates cache
  setTools(sessionId: string, value: boolean): void
  setAutoRead(sessionId: string, value: boolean): void
}
```

Rules:

- On chat open, the frontend receives the three toggle values from the session payload and hydrates the cache.
- Toggles persist across browser reloads and across devices, because they live on the server.
- Switching between existing chats shows each chat's own persisted state.
- Switching to a brand-new chat: the server computes persona-derived defaults at chat-create time (see "Backend changes"). The frontend simply receives them.
- Voice pipeline state, integrations config/health and conversation-mode state remain in their current stores (`voicePipelineStore`, `useIntegrationsStore`, `useConversationModeStore`). Only the three session toggles move into `cockpitStore`.

## Persona defaults on chat create

Defaults are computed **on the backend at session-create time**, not on the frontend. The algorithm is:

- `reasoning_override` → `None` (unchanged from today). Surfaced in the cockpit as `thinking = false`.
- `tools_enabled` → `true` if any active integration on this persona publishes at least one tool group; otherwise `false`. Rationale: a user who wires an integration to a persona clearly wants its tools active; making them toggle it on every chat is a support footgun.
- `auto_read` → `true` if `persona.voice_config` has both a TTS provider and a dialogue voice; otherwise `false`.

Once set, the user's overrides on that session are authoritative. Opening an existing chat never recomputes defaults.

## Backend changes

All changes are in the chat module's ChatSession Pydantic model and its API handlers.

### New fields

- **`tools_enabled: bool = False`** — master switch for tool use on this session. The request pipeline, when building the tool list for the LLM call, returns an empty list if `tools_enabled` is `False`, regardless of which tool groups would otherwise be available. Default `False` in the Pydantic model so pre-existing documents without the field deserialise cleanly.
- **`auto_read: bool = False`** — master switch for auto-play of assistant TTS on this session. The voice pipeline consults this flag when deciding whether to auto-play a completed assistant message. Default `False` in the Pydantic model.

### Removed field

- **`disabled_tool_groups` (`list[str]`) is removed.** Per-group toggling is no longer exposed in the UI; the master switch replaces it.

### Migration (no-wipe)

Because we are past the wipe cut-off, removal needs a migration. The one-shot script under `backend/migrations/`:

1. Iterates all ChatSession documents.
2. For each document, `$unset`s `disabled_tool_groups` if present.
3. Sets `tools_enabled` and `auto_read` on documents that don't have them, using the persona-default algorithm (see above), so that already-open chats carry sensible values instead of silently defaulting to `False`.
4. Is idempotent — re-running the migration over already-migrated documents is a no-op.

The Pydantic model defaults to `False` for both new fields so that a startup against an un-migrated database still deserialises without errors; the migration is a one-shot to promote existing chats to meaningful values rather than a correctness requirement for reads.

### API surface

No new endpoints. The existing session-update endpoint (already used for `reasoning_override`) accepts the two new fields. The frontend writes through on toggle and reads the fields out of the session payload on chat open.

### Request-pipeline integration

- Tool list construction: if `session.tools_enabled is False` → empty tool list to the LLM, full stop.
- Voice pipeline auto-play: reads `session.auto_read` on each completed assistant message.
- `session.reasoning_override` remains the authoritative flag for the LLM adapter; unchanged.

## Button behaviour

### `Attach` / `Camera` / `Browse`
- Simple action buttons, delegate to existing handlers. Native `title` tooltip only, no hover panel.
- Disabled when the current model cannot accept attachments (Attach, Camera) or permission is denied (Camera). Browse is always enabled.

### `Thinking`
- **Click:** toggles `cockpitStore.thinking` for the current session.
- **Hover panel:** title ("Reasoning · on/off"), one-sentence description, and the note "Session: remembered for this chat".
- **Disabled when:** the current model does not support reasoning. Panel text: "This model does not support reasoning."

### `Tools`
- **Click:** toggles `cockpitStore.tools` for the current session.
- **Hover panel:** title ("Tools · on/off · N available"), followed by the list of **groups only** (e.g. "Web search", "MCP · filesystem", "Integration · Lovense"). No individual tool names — users can ask the persona for details.
- **Disabled when:** no tool group is available (no web search, no MCP, no integration with tools). Panel text: "No tools available. Enable web search or connect an integration in persona settings."

### `Integrations`
- **Click:** opens a popover anchored to the button. Contents:
  - Heading "Active integrations".
  - One row per active integration with display name, connection/health state (coloured dot + short label) and a per-integration `Stop` button.
  - Footer: `Emergency stop — all` (destructive red button).
- **Hover (desktop):** the same popover opens on hover and stays open when the pointer moves into it (identical content, same interactive controls).
- **Mobile:** tap opens the popover as a bottom-sheet panel.
- **Disabled when:** the persona has no active integrations. Panel text: "No integrations active. Connect e.g. Lovense in persona settings."

### `Voice` (the magic button)

One button, six states, driven by two dimensions: live-mode on/off, and "is TTS playing right now".

| Context | Icon | Meaning | Click action |
|---------|------|---------|--------------|
| Normal chat, `autoRead` off, idle | `🔈` | "Auto-read is off" | Turn `autoRead` on |
| Normal chat, `autoRead` on, idle | `🔊` | "Auto-read is on" | Turn `autoRead` off |
| Normal chat, TTS playing | `⏹` | "Stop playback" | Stop playback; `autoRead` setting unchanged |
| Live, mic active, nothing playing | `🎤` | "Mic is listening" | Mute mic |
| Live, mic muted, nothing playing | `🎤̸` | "Mic is muted" | Unmute mic |
| Live, TTS playing | `⏹` | "Interrupt" | Stop playback; **mic state unchanged** |

Note: in live-mode, stopping playback does **not** automatically mute the mic. That is a deliberate second click.

- **Hover panel:** current status line, then a compact table of TTS provider, voice(s), mode, STT provider, sensitivity.
- **Disabled when:** the persona has no `voice_config` with a TTS provider and voice. Panel text: "This persona has no voice. Pick a TTS provider and a voice in persona settings."

### `Live`
- **Click:** toggles continuous voice mode via the existing `conversationModeStore`.
- **Hover panel:** title ("Continuous voice mode"), short description of what it does and when to use it.
- **Disabled when:** voice config is incomplete, or the user's account is not cleared for live mode. Panel text is context-dependent — either "Live mode needs TTS and STT on the persona." or "Live mode is not enabled for your account."

## Disabled-state visual

Disabled buttons render at low opacity, with a dashed border. They are not greyed-out icons that look broken — they are muted but present. Hover (or tap of the `Info` button on mobile) reveals the exact reason and the remedial step, phrased positively.

Colour legend (hover-panel accents only, not the button base):

| State | Accent |
|-------|--------|
| Active | button's semantic colour (gold / blue / purple / green) |
| Idle, enabled | neutral white at low alpha |
| Disabled | very low-alpha white on dashed outline |

## Mobile

Mobile differs from desktop in three respects only:

1. `Camera` button is present in the attachments group.
2. An `Info` (`ⓘ`) button is appended at the end of the row.
3. Hover panels are unreachable; the `Info` button opens a **bottom-sheet modal** as the substitute.

The modal is an accordion with one section per non-attachment button: Thinking, Tools, Integrations, Voice, Live. Each section is the exact content of its desktop hover panel, rendered vertically. Sections whose buttons are currently active start expanded; inactive sections start collapsed. The Integrations section contains the same per-integration `Stop` and `Emergency stop — all` controls.

The modal has its own close affordance; tapping outside or swiping down dismisses it.

## Strings

All UI strings in the cockpit are in English (British spelling). No German. This is consistent with the rest of the product's UI strings.

## Interactions with other subsystems

- **Tools on/off propagation.** The backend honours `session.tools_enabled`: when `False`, the tool list sent to the LLM is empty regardless of which integrations would otherwise contribute tools. This is how the user "experiences reasoning" on models that silently fall back to non-reasoning when tools are present.
- **Auto-read on/off propagation.** The backend voice pipeline reads `session.auto_read` when deciding whether to auto-play a completed assistant message. Persona voice config continues to provide the *default*, computed at chat-create time, not the runtime value.
- **Integrations emergency stop.** Reuses the existing `emergencyStop(config)` per plugin and the TTS audio cancel path.
- **Live mode.** Entering or leaving live mode does not clear the session toggles. A user who had Tools on in the normal chat keeps them on when they switch to live mode.

## Deletions

Removed from the existing UI as part of this change:

- The standalone integration-emergency-stop button rendered below the prompt input.
- The mobile-only wrench tray (`mobileToolsOpen` state and its collapsible `ToolToggles` wrapper).
- The separate `ConversationModeButton` in the topbar — its function moves into the cockpit `Live` button. (If the topbar placement is load-bearing for discoverability, revisit this after first user testing.)

## Manual verification

Before declaring this done, perform on a real device:

1. **Persona with Lovense integration:** open a new chat → Tools is on by default; hover Tools panel shows "Integration · Lovense" as a group. Toggle Tools off → integration tools absent from next request. Toggle back on.
2. **Persona without integration or voice:** open a chat → Tools disabled with "No tools available" message; Voice disabled with "No voice" message; Live disabled.
3. **Reasoning-only run:** persona with a tool-bringing integration; toggle Thinking on *and* Tools off; send a prompt → model receives no tools and responds with reasoning.
4. **Magic button cycle (normal chat):** `🔈` → click → `🔊`; send message → response auto-plays `⏹`; click `⏹` → playback stops, icon back to `🔊`.
5. **Magic button cycle (live mode):** enter live mode; speak; while assistant replies, click `⏹` → playback stops, mic still in whatever state it was. Click again → mic mutes. Click again → mic unmutes.
6. **Integrations popover:** click `🔌` → per-integration `Stop` cancels that integration; `Emergency stop — all` cancels all integrations and any in-flight TTS.
7. **Mobile info modal:** on a phone, tap `ⓘ` → bottom sheet shows five accordion sections; Integrations section contains working stop buttons; swipe down dismisses the sheet.
8. **Chat switching and persistence:** set Thinking on in chat X, switch to chat Y (different persona), back to chat X → chat X still shows Thinking on, chat Y shows its own persona-derived defaults. Reload the page → state is preserved (it is persisted server-side on the ChatSession).
9. **Disabled explanations:** every disabled button, when hovered or tapped via the info modal, shows the correct remedial text.
10. **Migration against pre-existing data:** run the backend against a MongoDB that still contains ChatSessions with `disabled_tool_groups` and no `tools_enabled` / `auto_read` fields → reads succeed without errors, the migration script promotes `tools_enabled` and `auto_read` to persona-derived values and removes `disabled_tool_groups`.

## Known unknowns

- Per-model capability metadata for the reasoning-plus-tools conflict is not yet decided (in-product integration vs. externally curated). Until it is, the cockpit does not enforce mutual exclusion and does not warn; the user is trusted to understand their model.
