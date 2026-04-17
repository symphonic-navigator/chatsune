# Voice Auto-Send Toggle & Configure-Voice Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a user-level "automatically send transcription" voice setting on a new Voice sub-tab, and a configure-voice fallback button on assistant messages when the Read button cannot be shown.

**Architecture:** Frontend-only. A new Voice sub-tab under Settings replaces the old embedded input-mode toggle; push-to-talk is hard-coded and the retired continuous branch in the transcription callback becomes the auto-send branch. The configure-voice fallback button re-uses the existing `openPersonaOverlay(personaId, tab?)` OutletContext callback (same mechanism `JournalBadge.tsx` already uses to open the Memories tab), so no new store is introduced.

**Tech Stack:** React 19, TypeScript, Vite, Tailwind, Zustand, React Router, Vitest + React Testing Library.

**Spec:** `devdocs/superpowers/specs/2026-04-18-voice-auto-send-and-configure-voice-fallback-design.md` — with two deliberate deviations:
1. No new `personaOverlayStore`. The existing `openPersonaOverlay` OutletContext covers this, and using it keeps all overlay-opening code paths uniform.
2. `PersonaOverlay.voiceEnabled` filter is widened from STT-only to `sttReady || ttsReady` so the Voice tab is reachable when a user has TTS configured but no STT (otherwise the fallback button would surface content without a matching tab button in the tab bar).

---

### Task 1: Extend voiceSettingsStore with auto-send + hard-coded PTT

**Files:**
- Modify: `frontend/src/features/voice/stores/voiceSettingsStore.ts`
- Test: `frontend/src/features/voice/stores/voiceSettingsStore.test.ts`

- [ ] **Step 1: Write the failing test**

Create the test file:

```ts
// frontend/src/features/voice/stores/voiceSettingsStore.test.ts
import { beforeEach, describe, expect, it } from 'vitest'

function resetStore() {
  // Wipe persisted state and force Zustand module cache reload
  window.localStorage.clear()
}

describe('voiceSettingsStore', () => {
  beforeEach(() => {
    resetStore()
    // Fresh module import each test so persist() re-reads localStorage
    // @ts-expect-error -- vitest module cache helper
    import.meta.vitest?.resetModules?.()
  })

  it('defaults autoSendTranscription to false', async () => {
    const { useVoiceSettingsStore } = await import('./voiceSettingsStore')
    expect(useVoiceSettingsStore.getState().autoSendTranscription).toBe(false)
  })

  it('setAutoSendTranscription toggles the flag', async () => {
    const { useVoiceSettingsStore } = await import('./voiceSettingsStore')
    useVoiceSettingsStore.getState().setAutoSendTranscription(true)
    expect(useVoiceSettingsStore.getState().autoSendTranscription).toBe(true)
  })

  it('forces inputMode to push-to-talk even if localStorage claims continuous', async () => {
    window.localStorage.setItem(
      'voice-settings',
      JSON.stringify({ state: { inputMode: 'continuous', autoSendTranscription: false }, version: 0 }),
    )
    const { useVoiceSettingsStore } = await import('./voiceSettingsStore')
    expect(useVoiceSettingsStore.getState().inputMode).toBe('push-to-talk')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && pnpm vitest run src/features/voice/stores/voiceSettingsStore.test.ts
```

Expected: three tests fail. The `autoSendTranscription` assertions fail because the field does not exist yet; the `inputMode` assertion fails because the current store returns `'continuous'` from localStorage.

- [ ] **Step 3: Extend the store**

Replace the contents of `frontend/src/features/voice/stores/voiceSettingsStore.ts` with:

```ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type InputMode = 'push-to-talk' | 'continuous'

interface VoiceSettingsState {
  inputMode: InputMode
  autoSendTranscription: boolean
  setInputMode(mode: InputMode): void
  setAutoSendTranscription(value: boolean): void
}

export const useVoiceSettingsStore = create<VoiceSettingsState>()(
  persist(
    (set) => ({
      inputMode: 'push-to-talk',
      autoSendTranscription: false,
      setInputMode: (inputMode) => set({ inputMode }),
      setAutoSendTranscription: (autoSendTranscription) => set({ autoSendTranscription }),
    }),
    {
      name: 'voice-settings',
      // Hard-code push-to-talk regardless of what older builds persisted.
      // The Continuous mode UI has been retired — VAD will replace it later.
      merge: (persisted, current) => ({
        ...current,
        ...(persisted as Partial<VoiceSettingsState>),
        inputMode: 'push-to-talk',
      }),
    },
  ),
)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && pnpm vitest run src/features/voice/stores/voiceSettingsStore.test.ts
```

Expected: three tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/voice/stores/voiceSettingsStore.ts \
         frontend/src/features/voice/stores/voiceSettingsStore.test.ts
git commit -m "Add auto-send flag and pin push-to-talk in voice settings store"
```

---

### Task 2: Register Voice sub-tab in userModalTree

**Files:**
- Modify: `frontend/src/app/components/user-modal/userModalTree.ts`

- [ ] **Step 1: Add 'voice' to SubTabId**

In `userModalTree.ts`, extend the `SubTabId` union (currently defined around lines 15-33) so `'voice'` is part of the `settings` group. After the existing `| 'display'` line add:

```ts
  | 'voice'
```

- [ ] **Step 2: Add Voice entry to the settings children array**

In the `TABS_TREE` constant (around line 63-73), insert a Voice entry **immediately after** the existing Display entry so the settings children read:

```ts
    children: [
      { id: 'llm-providers',          label: 'LLM Providers' },
      { id: 'community-provisioning', label: 'Community Provisioning' },
      { id: 'models',                 label: 'Models' },
      { id: 'api-keys',               label: 'API-Keys' },
      { id: 'mcp',                    label: 'MCP' },
      { id: 'integrations',           label: 'Integrations' },
      { id: 'display',                label: 'Display' },
      { id: 'voice',                  label: 'Voice' },
    ],
```

- [ ] **Step 3: Type-check**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: one error — `UserModal.tsx` does not yet render anything for `contentKey === 'voice'`. That error is resolved in Task 4. Keep going.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/user-modal/userModalTree.ts
git commit -m "Register Voice sub-tab after Display in user modal navigation"
```

---

### Task 3: Create VoiceTab component

**Files:**
- Create: `frontend/src/app/components/user-modal/VoiceTab.tsx`
- Test: `frontend/src/app/components/user-modal/__tests__/VoiceTab.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/app/components/user-modal/__tests__/VoiceTab.test.tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { VoiceTab } from '../VoiceTab'
import { useVoiceSettingsStore } from '../../../../features/voice/stores/voiceSettingsStore'

describe('VoiceTab', () => {
  beforeEach(() => {
    useVoiceSettingsStore.setState({ autoSendTranscription: false })
  })

  it('shows the auto-send toggle with the store default (Off)', () => {
    render(<VoiceTab />)
    expect(screen.getByRole('button', { name: /automatically send transcription/i })).toHaveTextContent(/off/i)
  })

  it('flips the store flag when clicked', async () => {
    const user = userEvent.setup()
    render(<VoiceTab />)
    await user.click(screen.getByRole('button', { name: /automatically send transcription/i }))
    expect(useVoiceSettingsStore.getState().autoSendTranscription).toBe(true)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd frontend && pnpm vitest run src/app/components/user-modal/__tests__/VoiceTab.test.tsx
```

Expected: failure because `VoiceTab` does not exist.

- [ ] **Step 3: Implement VoiceTab**

```tsx
// frontend/src/app/components/user-modal/VoiceTab.tsx
import { useVoiceSettingsStore } from '../../../features/voice/stores/voiceSettingsStore'

const LABEL = 'block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono'

export function VoiceTab() {
  const autoSend = useVoiceSettingsStore((s) => s.autoSendTranscription)
  const setAutoSend = useVoiceSettingsStore((s) => s.setAutoSendTranscription)

  return (
    <div className="flex flex-col gap-6 p-6 max-w-xl overflow-y-auto">
      <div>
        <label className={LABEL}>Automatically send transcription</label>
        <p className="text-[11px] text-white/40 font-mono mb-2 leading-relaxed">
          When on, your transcribed speech is sent as soon as you release
          Push-to-Talk — no extra tap.
        </p>
        <button
          type="button"
          aria-label="Automatically send transcription"
          onClick={() => setAutoSend(!autoSend)}
          className={[
            'px-3.5 py-1.5 rounded-lg text-[11px] font-mono transition-all border',
            autoSend
              ? 'border-gold/60 bg-gold/12 text-gold'
              : 'border-white/8 bg-transparent text-white/40 hover:text-white/65 hover:border-white/20',
          ].join(' ')}
        >
          {autoSend ? 'On' : 'Off'}
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd frontend && pnpm vitest run src/app/components/user-modal/__tests__/VoiceTab.test.tsx
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/user-modal/VoiceTab.tsx \
         frontend/src/app/components/user-modal/__tests__/VoiceTab.test.tsx
git commit -m "Add VoiceTab with automatically-send-transcription toggle"
```

---

### Task 4: Wire VoiceTab into UserModal

**Files:**
- Modify: `frontend/src/app/components/user-modal/UserModal.tsx`

- [ ] **Step 1: Add VoiceTab import**

Near the other tab imports at the top of `UserModal.tsx` (around line 2-17), add:

```tsx
import { VoiceTab } from './VoiceTab'
```

- [ ] **Step 2: Render VoiceTab for the 'voice' sub-tab**

In the tab-content section (around line 281-297), insert this line immediately **after** the existing `display` case:

```tsx
          {contentKey === 'voice' && <VoiceTab />}
```

- [ ] **Step 3: Type-check**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: zero errors (Task 2's type error is now resolved).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/user-modal/UserModal.tsx
git commit -m "Render VoiceTab under Settings > Voice in user modal"
```

---

### Task 5: Remove old VoiceSettings embed from Display tab

**Files:**
- Modify: `frontend/src/app/components/user-modal/SettingsTab.tsx`
- Delete: `frontend/src/features/voice/components/VoiceSettings.tsx`

- [ ] **Step 1: Remove the import from SettingsTab**

In `SettingsTab.tsx`, delete line 2:

```tsx
import { VoiceSettings } from '../../../features/voice/components/VoiceSettings'
```

- [ ] **Step 2: Remove the embed and its divider**

In `SettingsTab.tsx`, delete lines 154-156 entirely:

```tsx
      <div className="border-t border-white/8 pt-6">
        <VoiceSettings />
      </div>
```

- [ ] **Step 3: Delete the unused component file**

```bash
rm frontend/src/features/voice/components/VoiceSettings.tsx
```

- [ ] **Step 4: Type-check and lint**

```bash
cd frontend && pnpm tsc --noEmit && pnpm lint
```

Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/app/components/user-modal/SettingsTab.tsx \
         frontend/src/features/voice/components/VoiceSettings.tsx
git commit -m "Remove Input Mode buttons from Display tab; Voice settings live under Voice now"
```

---

### Task 6: Rewire ChatView transcription callback to auto-send flag

**Files:**
- Modify: `frontend/src/features/chat/ChatView.tsx`

- [ ] **Step 1: Replace the store selector**

Around line 108, replace:

```tsx
  const voiceInputMode = useVoiceSettingsStore((s) => s.inputMode)
```

with:

```tsx
  const autoSendTranscription = useVoiceSettingsStore((s) => s.autoSendTranscription)
```

- [ ] **Step 2: Replace the transcription callback branch**

Around lines 605-626, the callback currently branches on `voiceInputMode === 'continuous'`. Replace that entire `useEffect` body with:

```tsx
  // Voice pipeline callbacks — always registered; the pipeline itself guards against missing engines
  useEffect(() => {
    voicePipeline.setCallbacks({
      onStateChange: setPipelineState,
      onTranscription: (text) => {
        setTranscription(text)
        if (autoSendTranscription && text.trim()) {
          // Auto-send mode: briefly show the transcription, then send.
          setTimeout(() => {
            handleSend(text)
            setTranscription('')
          }, 800)
        } else {
          // Default (push-to-talk review) mode: put text in input for editing before send.
          chatInputRef.current?.setText(text)
          setTimeout(() => setTranscription(''), 1500)
        }
      },
    })
    return () => voicePipeline.dispose()
  }, [autoSendTranscription, setPipelineState])
```

Note: the existing code uses `handleSend` inside the callback but does not list it in deps — keep the existing dep style (`[autoSendTranscription, setPipelineState]`) to avoid unrelated refactors.

- [ ] **Step 3: Build**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 4: Manual smoke test**

Start the dev server, sign in, open a chat with a persona:

```bash
cd frontend && pnpm dev
```

Steps:
1. Open User Modal → Settings → Voice. The "Automatically send transcription" toggle shows "Off".
2. Hold the Push-to-Talk button, speak, release. The transcription lands in the input field; you send manually. (= existing behaviour)
3. Turn the toggle "On". Repeat PTT. The transcription flashes in the overlay for ~800 ms and is then sent automatically without a manual tap.
4. Display tab no longer shows the Push-to-Talk / Continuous button group.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/ChatView.tsx
git commit -m "Gate transcription auto-send on voiceSettings flag; retire continuous branch"
```

---

### Task 7: Widen voiceEnabled filter in PersonaOverlay to STT or TTS

**Files:**
- Modify: `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx`

- [ ] **Step 1: Add ttsRegistry import**

Around line 16, alongside the existing `sttRegistry` import:

```tsx
import { sttRegistry, ttsRegistry } from '../../../features/voice/engines/registry'
```

(If the registry file does not re-export both from the same module, keep two separate imports: `import { sttRegistry } from '...'` plus `import { ttsRegistry } from '...'`. Verify by opening `frontend/src/features/voice/engines/registry.ts` first.)

- [ ] **Step 2: Update the voiceEnabled flag**

Around line 122, replace:

```tsx
  const voiceEnabled = !!sttRegistry.active()?.isReady()
```

with:

```tsx
  const voiceEnabled = !!(sttRegistry.active()?.isReady() || ttsRegistry.active()?.isReady())
```

- [ ] **Step 3: Build**

```bash
cd frontend && pnpm tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/persona-overlay/PersonaOverlay.tsx
git commit -m "Show persona Voice tab when either STT or TTS engine is ready"
```

---

### Task 8: Add configure-voice fallback to ReadAloudButton

**Files:**
- Modify: `frontend/src/features/voice/components/ReadAloudButton.tsx`

- [ ] **Step 1: Import OutletContext hook**

At the top of `ReadAloudButton.tsx` add:

```tsx
import { useOutletContext } from 'react-router-dom'
```

- [ ] **Step 2: Replace the null-return guard with the fallback button**

Around line 226 the current guard is:

```tsx
  if (!ttsReady || !voiceId) return null
```

Replace it, and the subsequent `return` that renders the full Read button, so the component becomes:

```tsx
  const outlet = useOutletContext<{
    openPersonaOverlay: (personaId: string | null, tab?: string) => void
  }>()

  const personaId = persona?.id ?? null

  if (!ttsReady || !voiceId) {
    // Fallback — show a Configure-voice button that jumps to the persona's Voice tab.
    // When we have no persona id, there is nothing meaningful to configure, so bail.
    if (!personaId) return null
    return (
      <button
        type="button"
        onClick={() => outlet.openPersonaOverlay(personaId, 'voice')}
        title="Configure voice"
        aria-label="Configure voice"
        className="flex items-center gap-1 text-[11px] text-white/20 transition-colors hover:text-white/45"
      >
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
          <path d="M2 5.5V8.5H4.5L7.5 11V3L4.5 5.5H2Z" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" />
          <path d="M9.5 4.5C10.3 5.3 10.3 8.7 9.5 9.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
          <path d="M11 3C12.5 4.5 12.5 9.5 11 11" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
        </svg>
        Configure voice
      </button>
    )
  }

  const displayState = isActive ? state : 'idle'
  const label = displayState === 'synthesising' ? 'Preparing...' : displayState === 'playing' ? 'Stop' : 'Read'
  const active = displayState !== 'idle'

  return (
    <button type="button" onClick={handleClick}
      className={`flex items-center gap-1 text-[11px] transition-colors ${active ? 'text-gold' : 'text-white/25 hover:text-white/50'}`}
      title={label}>
      {displayState === 'synthesising' ? (
        <span className="inline-block h-3 w-3 animate-spin rounded-full border-[1.5px] border-gold/30 border-t-gold" />
      ) : displayState === 'playing' ? (
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none"><rect x="2" y="2" width="10" height="10" rx="1.5" fill="currentColor" /></svg>
      ) : (
        <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
          <path d="M2 5.5V8.5H4.5L7.5 11V3L4.5 5.5H2Z" stroke="currentColor" strokeWidth="1.1" strokeLinejoin="round" />
          <path d="M9.5 4.5C10.3 5.3 10.3 8.7 9.5 9.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
          <path d="M11 3C12.5 4.5 12.5 9.5 11 11" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
        </svg>
      )}
      {label}
    </button>
  )
```

- [ ] **Step 3: Drop the voiceEnabled gate from the ReadAloudButton render site**

Context: the `voiceEnabled` prop threaded through `MessageList` and `AssistantMessage` is derived from STT-readiness only (`ChatView.tsx:109`). It is still used correctly by `ChatInput` for the mic button, but it over-gates `ReadAloudButton`: with today's code the button vanishes whenever the user has no STT, even if they have a working TTS integration. For our fallback to ever appear we must stop gating the button's render site on `voiceEnabled`. The button itself now decides (Read / Fallback / `null`).

`voiceEnabled` remains a valid prop on `AssistantMessage` (other code in the file or callers may rely on it) — do **not** remove the prop. Only the one gate on the button render changes.

In `AssistantMessage.tsx` around line 140, replace:

```tsx
              {voiceEnabled && messageId && (
                <ReadAloudButton messageId={messageId} content={effectiveContent} persona={persona} />
              )}
```

with:

```tsx
              {messageId && (
                <ReadAloudButton messageId={messageId} content={effectiveContent} persona={persona} />
              )}
```

Leave the `voiceEnabled` prop declaration and destructuring as-is — `ChatInput` and `ChatView` still depend on it. If the lint run in Step 4 surfaces an "unused variable" warning for `voiceEnabled` in `AssistantMessage`, it means nothing else inside the file uses it; in that case remove only the destructured local binding (keep the prop on the interface so callers continue to type-check).

- [ ] **Step 4: Build and lint**

```bash
cd frontend && pnpm tsc --noEmit && pnpm lint
```

Expected: zero errors, zero warnings from the changed files.

- [ ] **Step 5: Manual smoke test**

```bash
cd frontend && pnpm dev
```

1. With a persona that **has** a TTS integration and `voice_id` set: the Read button shows on assistant messages exactly as before.
2. With a persona that has a TTS integration but **no** `voice_id`: the "Configure voice" button shows in place of Read. Clicking it opens the persona overlay on the Voice tab.
3. With **no** TTS integration configured at all: the "Configure voice" button shows. Clicking it opens the persona overlay on the Voice tab (empty voice dropdown state). The tab button appears in the tab bar (Task 7's widening made this possible).
4. Other overlay entry points (personas list, Topbar persona menu, Memories link from JournalBadge) still work.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/voice/components/ReadAloudButton.tsx \
         frontend/src/features/chat/AssistantMessage.tsx
git commit -m "Add Configure-voice fallback on assistant messages when Read is unavailable"
```

---

### Task 9: Full-build verification and end-to-end smoke

**Files:** none touched.

- [ ] **Step 1: Clean build**

```bash
cd frontend && pnpm run build
```

Expected: build succeeds, zero TypeScript errors, zero unused-import warnings.

- [ ] **Step 2: Run all frontend tests**

```bash
cd frontend && pnpm vitest run
```

Expected: all existing tests continue to pass; the new `voiceSettingsStore` and `VoiceTab` tests pass.

- [ ] **Step 3: End-to-end smoke in the browser**

Start the dev server (`pnpm dev`) and walk through every spec-level acceptance criterion in one session:

1. User Modal → Settings: Voice tab appears after Display with the Auto-send toggle (default Off). Display tab no longer has Input Mode buttons.
2. Toggle Off → PTT transcription lands in the input field.
3. Toggle On → PTT transcription flashes in the overlay ~800 ms then is sent automatically.
4. Toggle persists across a full page reload.
5. Assistant message with fully configured voice: Read button visible.
6. Assistant message with TTS integration but no persona voice: Configure voice button visible; click opens persona overlay on Voice tab.
7. Assistant message with no TTS integration at all: Configure voice button visible; click opens persona overlay on Voice tab with the voice dropdown empty.
8. Existing persona-overlay entry points (personas list, Topbar menu, JournalBadge Memories link) still work.

- [ ] **Step 4: No additional commit needed**

This task is verification-only; merging happens per the project's standard post-implementation flow (see `CLAUDE.md` — "Please always merge to master after implementation").
