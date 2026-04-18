# Tentative Barge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current one-shot destructive barge with a two-stage commit so non-speech noise during TTS no longer aborts the assistant's reply.

**Architecture:** Introduce a `TENTATIVE_BARGE` state in `useConversationMode` guarded by a monotonic `bargeId`. On VAD speech-start: mute audio but keep synthesis, LLM stream, and queue alive. On VAD speech-end: wait for STT. Non-empty transcript → confirm barge (current tear-down path). Empty transcript → resume from anchor. The anchor is the currently-playing queue entry held inside `audioPlayback` between `mute()` and `resumeFromMute()`.

**Tech Stack:** TypeScript, React hooks, Vitest, Web Audio API, Silero VAD (via `@ricky0123/vad-web`).

**Spec:** [`devdocs/superpowers/specs/2026-04-18-tentative-barge-design.md`](../specs/2026-04-18-tentative-barge-design.md)

---

## File Structure

**Modify:**
- `frontend/src/features/voice/infrastructure/audioPlayback.ts` — add `mute()` / `resumeFromMute()` / `isMuted()`; store `mutedEntry` while muted.
- `frontend/src/features/voice/hooks/useConversationMode.ts` — replace `executeBarge` with tentative/confirm/resume logic; add `bargeId` ref and STT staleness guard.
- `frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts` — new tests for mute/resume semantics.

**Create:**
- `frontend/src/features/voice/hooks/__tests__/useConversationMode.bargeLogic.test.ts` — pure state-machine tests for the barge decision function (extracted during Task 3).

No backend changes. No `shared/` changes.

---

## Task 1: Add mute/resume to audioPlayback

Non-destructive counterpart to `stopAll()`. `mute()` stops the current source and stores its entry without clearing the queue or firing `onFinished`. `resumeFromMute()` re-enqueues the stored entry at the front of the queue and restarts playback.

**Files:**
- Modify: `frontend/src/features/voice/infrastructure/audioPlayback.ts`
- Test: `frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts`

- [ ] **Step 1.1: Write failing test — mute stops current source but keeps queue**

Append this `describe` block to the end of `audioPlayback.test.ts`:

```ts
describe('audioPlayback — mute / resumeFromMute', () => {
  it('mute stops the current source but preserves the queue', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    // First segment is playing; second is in the queue.
    expect(sources[0].stop).not.toHaveBeenCalled()

    audioPlayback.mute()

    expect(sources[0].stop).toHaveBeenCalledTimes(1)
    expect(audioPlayback.isMuted()).toBe(true)
    expect(audioPlayback.isPlaying()).toBe(false)
  })

  it('resumeFromMute replays the muted segment from its start, then continues the queue', async () => {
    const onSegmentStart = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart, onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.enqueue(new Float32Array(10), { ...SEGMENT, text: 'second' })
    expect(onSegmentStart).toHaveBeenCalledTimes(1)
    expect(onSegmentStart).toHaveBeenNthCalledWith(1, SEGMENT)

    audioPlayback.mute()
    audioPlayback.resumeFromMute()
    await Promise.resolve() // playNext is async

    expect(audioPlayback.isMuted()).toBe(false)
    // The muted segment is played again (from the start).
    expect(onSegmentStart).toHaveBeenCalledTimes(2)
    expect(onSegmentStart).toHaveBeenNthCalledWith(2, SEGMENT)

    // When it finishes, the second segment plays.
    finishPlayback(1)
    await Promise.resolve()
    expect(onSegmentStart).toHaveBeenCalledTimes(3)
    expect(onSegmentStart).toHaveBeenNthCalledWith(3, { ...SEGMENT, text: 'second' })
  })

  it('resumeFromMute is a no-op when nothing is muted', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    expect(() => audioPlayback.resumeFromMute()).not.toThrow()
    expect(audioPlayback.isMuted()).toBe(false)
  })

  it('mute is a no-op when nothing is playing', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.mute()
    expect(audioPlayback.isMuted()).toBe(false)
  })

  it('mute does not fire onFinished even if streamClosed is set', () => {
    const onFinished = vi.fn()
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.closeStream()

    audioPlayback.mute()

    expect(onFinished).not.toHaveBeenCalled()
  })

  it('stopAll after mute clears the muted entry', () => {
    audioPlayback.setCallbacks({ onSegmentStart: vi.fn(), onFinished: vi.fn() })
    audioPlayback.enqueue(new Float32Array(10), SEGMENT)
    audioPlayback.mute()
    expect(audioPlayback.isMuted()).toBe(true)

    audioPlayback.stopAll()

    expect(audioPlayback.isMuted()).toBe(false)
  })
})
```

- [ ] **Step 1.2: Run the new tests to verify they fail**

Run: `cd frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/audioPlayback.test.ts`

Expected: the six new cases fail (`mute is not a function`, `resumeFromMute is not a function`, `isMuted is not a function`). Existing tests still pass.

- [ ] **Step 1.3: Implement `mute` / `resumeFromMute` / `isMuted`**

In `frontend/src/features/voice/infrastructure/audioPlayback.ts`, add a field and three methods on `AudioPlaybackImpl`. The full class after the change looks like:

```ts
class AudioPlaybackImpl {
  private queue: QueueEntry[] = []
  private ctx: AudioContext | null = null
  private currentSource: AudioBufferSourceNode | null = null
  private currentEntry: QueueEntry | null = null
  private mutedEntry: QueueEntry | null = null
  private callbacks: AudioPlaybackCallbacks | null = null
  private playing = false
  private streamClosed = false
  private pendingGapTimer: ReturnType<typeof setTimeout> | null = null

  setCallbacks(callbacks: AudioPlaybackCallbacks): void { this.callbacks = callbacks }

  enqueue(audio: Float32Array, segment: SpeechSegment): void {
    this.queue.push({ audio, segment })
    if (!this.playing && this.pendingGapTimer === null && this.mutedEntry === null) this.playNext()
  }

  closeStream(): void {
    this.streamClosed = true
    if (!this.playing && this.queue.length === 0 && this.pendingGapTimer === null && this.mutedEntry === null) {
      this.callbacks?.onFinished()
    }
  }

  stopAll(): void {
    this.queue = []
    this.streamClosed = false
    this.mutedEntry = null
    if (this.pendingGapTimer !== null) {
      clearTimeout(this.pendingGapTimer)
      this.pendingGapTimer = null
    }
    if (this.currentSource) {
      this.currentSource.onended = null
      try { this.currentSource.stop() } catch { /* already stopped */ }
      this.currentSource = null
    }
    this.currentEntry = null
    this.playing = false
  }

  /**
   * Non-destructive pause used by Tentative Barge. Stops the current source
   * and remembers its entry so resumeFromMute() can replay it from the
   * start. The queue and streamClosed flag are preserved. Idempotent.
   */
  mute(): void {
    if (this.mutedEntry !== null) return // already muted
    if (!this.currentSource || !this.currentEntry) return // nothing to mute
    this.mutedEntry = this.currentEntry
    this.currentSource.onended = null // don't advance the queue
    try { this.currentSource.stop() } catch { /* already stopped */ }
    this.currentSource = null
    this.currentEntry = null
    this.playing = false
    if (this.pendingGapTimer !== null) {
      clearTimeout(this.pendingGapTimer)
      this.pendingGapTimer = null
    }
  }

  /**
   * Resume after a mute(). Re-queues the muted entry at the head of the
   * queue and kicks playback. No-op if nothing is muted.
   */
  resumeFromMute(): void {
    const entry = this.mutedEntry
    if (!entry) return
    this.mutedEntry = null
    this.queue.unshift(entry)
    if (!this.playing && this.pendingGapTimer === null) this.playNext()
  }

  isMuted(): boolean { return this.mutedEntry !== null }

  skipCurrent(): void {
    if (this.currentSource) {
      try { this.currentSource.stop() } catch { /* already stopped */ }
      this.currentSource = null
    }
  }

  private scheduleNext(): void {
    const gap = this.callbacks?.gapMs ?? 0
    if (gap > 0) {
      this.pendingGapTimer = setTimeout(() => {
        this.pendingGapTimer = null
        this.playNext()
      }, gap)
    } else {
      this.playNext()
    }
  }

  private async playNext(): Promise<void> {
    const entry = this.queue.shift()
    if (!entry) {
      this.playing = false
      this.currentEntry = null
      if (this.streamClosed) this.callbacks?.onFinished()
      return
    }

    this.playing = true
    this.currentEntry = entry
    this.callbacks?.onSegmentStart(entry.segment)

    try {
      if (!this.ctx || this.ctx.state === 'closed') {
        this.ctx = new AudioContext({ sampleRate: 24_000 })
      }
      if (this.ctx.state === 'suspended') {
        await this.ctx.resume()
      }

      const speed = entry.segment.speed ?? 1.0
      const pitch = entry.segment.pitch ?? 0
      const needsModulation = speed !== 1.0 || pitch !== 0

      const bufferLength = needsModulation
        ? entry.audio.length + MODULATION_TAIL_SAMPLES
        : entry.audio.length
      const buffer = this.ctx.createBuffer(1, bufferLength, SAMPLE_RATE)
      buffer.getChannelData(0).set(entry.audio)

      const source = this.ctx.createBufferSource()
      source.buffer = buffer

      let modNode: AudioNode | null = null
      if (needsModulation) {
        const ready = await ensureSoundTouchReady(this.ctx)
        if (ready) {
          modNode = createModulationNode(this.ctx, speed, pitch)
        }
      }

      if (modNode) {
        source.playbackRate.value = speed
        source.connect(modNode)
        modNode.connect(this.ctx.destination)
      } else {
        source.connect(this.ctx.destination)
      }

      this.currentSource = source

      source.onended = () => {
        this.currentSource = null
        this.currentEntry = null
        if (modNode) {
          try { modNode.disconnect() } catch { /* ignore */ }
        }
        this.scheduleNext()
      }

      source.start()
    } catch (err) {
      console.error('[AudioPlayback] Failed to play segment:', err)
      this.currentSource = null
      this.currentEntry = null
      this.scheduleNext()
    }
  }

  isPlaying(): boolean { return this.playing }

  dispose(): void {
    this.stopAll()
    if (this.ctx && this.ctx.state !== 'closed') {
      this.ctx.close()
    }
    this.ctx = null
    this.callbacks = null
  }
}
```

Key changes vs the original:
- New fields `currentEntry` and `mutedEntry`.
- `currentEntry` is set in `playNext` and cleared in `onended` / on error / on `stopAll`.
- `enqueue` and `closeStream` treat `mutedEntry !== null` like an active playback — they must not auto-start or fire `onFinished`.
- `stopAll` also wipes `mutedEntry` so Confirmed Barge cleanly discards it.

- [ ] **Step 1.4: Run the full test file**

Run: `cd frontend && pnpm vitest run src/features/voice/infrastructure/__tests__/audioPlayback.test.ts`

Expected: all tests pass (old + new).

- [ ] **Step 1.5: Commit**

```bash
git add frontend/src/features/voice/infrastructure/audioPlayback.ts \
        frontend/src/features/voice/infrastructure/__tests__/audioPlayback.test.ts
git commit -m "Add non-destructive mute/resume to audioPlayback"
```

---

## Task 2: Extract pure barge-decision logic from useConversationMode

The current `executeBarge` / `handleSpeechStart` / `handleSpeechEnd` / `transcribeAndSend` are deeply entangled with React refs and side-effect calls. Before we change the state machine, extract a pure decision function we can test in isolation.

**Files:**
- Create: `frontend/src/features/voice/hooks/bargeDecision.ts`
- Create: `frontend/src/features/voice/hooks/__tests__/bargeDecision.test.ts`

- [ ] **Step 2.1: Write the failing tests**

Create `frontend/src/features/voice/hooks/__tests__/bargeDecision.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { decideSttOutcome } from '../bargeDecision'

describe('decideSttOutcome', () => {
  it('returns "resume" when the transcript is empty and bargeId is still current', () => {
    expect(decideSttOutcome({ transcript: '', sttBargeId: 3, currentBargeId: 3 }))
      .toBe('resume')
  })

  it('returns "resume" when the transcript is only whitespace', () => {
    expect(decideSttOutcome({ transcript: '   \n ', sttBargeId: 1, currentBargeId: 1 }))
      .toBe('resume')
  })

  it('returns "confirm" when the transcript is non-empty and bargeId matches', () => {
    expect(decideSttOutcome({ transcript: 'hello', sttBargeId: 2, currentBargeId: 2 }))
      .toBe('confirm')
  })

  it('returns "stale" when a newer barge has started, regardless of transcript', () => {
    expect(decideSttOutcome({ transcript: 'hello', sttBargeId: 1, currentBargeId: 2 }))
      .toBe('stale')
    expect(decideSttOutcome({ transcript: '', sttBargeId: 1, currentBargeId: 2 }))
      .toBe('stale')
  })
})
```

- [ ] **Step 2.2: Run to confirm failure**

Run: `cd frontend && pnpm vitest run src/features/voice/hooks/__tests__/bargeDecision.test.ts`

Expected: `Cannot find module '../bargeDecision'`.

- [ ] **Step 2.3: Implement the pure decider**

Create `frontend/src/features/voice/hooks/bargeDecision.ts`:

```ts
/**
 * Pure decision function for how to handle an STT result returned during a
 * Tentative Barge. Kept free of React / audio dependencies so it can be
 * unit-tested without stubs.
 *
 *   stale   — a newer barge was started while STT was running; drop the
 *             result and do nothing.
 *   resume  — STT returned no text for the current barge; unmute and carry
 *             on with the assistant's reply.
 *   confirm — STT returned text for the current barge; this is a real
 *             barge. Cancel the assistant's reply and send the utterance.
 */
export type SttOutcome = 'stale' | 'resume' | 'confirm'

export interface SttDecisionInput {
  transcript: string
  sttBargeId: number
  currentBargeId: number
}

export function decideSttOutcome({ transcript, sttBargeId, currentBargeId }: SttDecisionInput): SttOutcome {
  if (sttBargeId !== currentBargeId) return 'stale'
  if (transcript.trim().length === 0) return 'resume'
  return 'confirm'
}
```

- [ ] **Step 2.4: Run to confirm pass**

Run: `cd frontend && pnpm vitest run src/features/voice/hooks/__tests__/bargeDecision.test.ts`

Expected: 4 tests pass.

- [ ] **Step 2.5: Commit**

```bash
git add frontend/src/features/voice/hooks/bargeDecision.ts \
        frontend/src/features/voice/hooks/__tests__/bargeDecision.test.ts
git commit -m "Add pure decision function for tentative-barge STT outcomes"
```

---

## Task 3: Wire Tentative Barge into useConversationMode

Replace the immediate tear-down in `executeBarge` with a mute-only path, and move the cancellation calls into `transcribeAndSend` where we know whether STT returned text.

**Files:**
- Modify: `frontend/src/features/voice/hooks/useConversationMode.ts`

- [ ] **Step 3.1: Add imports and the bargeId ref**

Change the import block at the top of `useConversationMode.ts` to include `decideSttOutcome`:

```ts
import { useCallback, useEffect, useRef } from 'react'
import { useConversationModeStore } from '../stores/conversationModeStore'
import { voicePipeline } from '../pipeline/voicePipeline'
import { audioCapture } from '../infrastructure/audioCapture'
import { audioPlayback } from '../infrastructure/audioPlayback'
import { cancelStreamingAutoRead } from '../pipeline/streamingAutoReadControl'
import { useChatStore } from '../../../core/store/chatStore'
import { chatApi } from '../../../core/api/chat'
import { useNotificationStore } from '../../../core/store/notificationStore'
import { setActiveReader } from '../components/ReadAloudButton'
import { sttRegistry } from '../engines/registry'
import { decideSttOutcome } from './bargeDecision'
```

Inside the hook body, just after `pendingBargeRef` (around line 148), add:

```ts
  // Monotonic counter that identifies the current barge cycle. Incremented
  // every time a new speech-start is accepted (past the 150 ms misfire
  // window). Any async result (STT promise) that carries a stale bargeId is
  // ignored. This is the serialisation primitive for Tentative Barge.
  const bargeIdRef = useRef(0)
  // True while we are in TENTATIVE_BARGE — i.e. audio is muted but not yet
  // torn down. Used by handleSpeechStart to tell a "fresh" barge from a
  // repeat VAD re-trigger during the same user utterance.
  const tentativeRef = useRef(false)
```

- [ ] **Step 3.2: Replace `executeBarge` with a tentative-barge entry**

Replace the existing `executeBarge` definition (lines 157-166) with:

```ts
  /**
   * Enter TENTATIVE_BARGE: mute playback instantly, but leave the TTS
   * synthesis pipeline, the sentence queue, and the LLM stream alone.
   * The fate of the barge is decided once STT returns.
   *
   * If we are already in TENTATIVE_BARGE (user re-triggered VAD mid-
   * utterance), we only bump bargeId so any in-flight STT becomes stale;
   * the earliest mute/anchor is kept (audioPlayback.mute is idempotent).
   */
  const executeBarge = useCallback(() => {
    pendingBargeRef.current = null
    bargeIdRef.current += 1
    const current = phaseRef.current
    if (current === 'thinking' || current === 'speaking') {
      audioPlayback.mute()
      tentativeRef.current = true
    }
    setPhase('user-speaking')
  }, [setPhase])
```

Note: the `cancelStreamingAutoRead()` and `audioPlayback.stopAll()` and `setActiveReader(null, 'idle')` calls are gone from this path. They move into `transcribeAndSend` (below), only on Confirmed Barge.

- [ ] **Step 3.3: Update `transcribeAndSend` to commit or resume based on STT**

Replace the existing `transcribeAndSend` (lines 99-138) with:

```ts
  const transcribeAndSend = useCallback(async (audio: Float32Array): Promise<void> => {
    if (!activeRef.current) return
    const sttBargeId = bargeIdRef.current

    if (audio.length === 0) {
      // No audio captured (e.g. held-release with nothing buffered). Treat
      // as "no barge confirmed" — resume if we're muted, otherwise just
      // return to listening.
      if (tentativeRef.current) {
        tentativeRef.current = false
        audioPlayback.resumeFromMute()
      } else {
        setPhase('listening')
      }
      return
    }

    setPhase('transcribing')
    const stt = sttRegistry.active()
    if (!stt) {
      useNotificationStore.getState().addNotification({
        level: 'error',
        title: 'Conversational mode stopped',
        message: 'No transcription engine is available.',
      })
      exitStore()
      return
    }
    try {
      const result = await stt.transcribe(audio)
      if (!activeRef.current) return

      const outcome = decideSttOutcome({
        transcript: result.text,
        sttBargeId,
        currentBargeId: bargeIdRef.current,
      })

      if (outcome === 'stale') {
        // A newer barge has taken over while STT was running. Do nothing:
        // that newer cycle will run its own STT and decide.
        return
      }

      if (outcome === 'resume') {
        // No text → the noise was not a real barge. Resume playback.
        if (tentativeRef.current) {
          tentativeRef.current = false
          audioPlayback.resumeFromMute()
        } else {
          setPhase('listening')
        }
        return
      }

      // outcome === 'confirm' — commit to the barge.
      if (tentativeRef.current) {
        tentativeRef.current = false
        cancelStreamingAutoRead()   // kills sentencer session + stopAll internally
        setActiveReader(null, 'idle')
      }
      setPhase('thinking')
      onSendRef.current(result.text.trim())
    } catch (err) {
      console.error('[ConversationMode] Transcription failed:', err)
      useNotificationStore.getState().addNotification({
        level: 'error',
        title: 'Transcription failed',
        message: "Couldn't transcribe audio — check the console for details.",
      })
      if (activeRef.current) {
        // On STT failure, err on the destructive side: tear down so the
        // user isn't left with muted playback forever.
        if (tentativeRef.current) {
          tentativeRef.current = false
          cancelStreamingAutoRead()
          setActiveReader(null, 'idle')
        }
        setPhase('listening')
      }
    }
  }, [setPhase, exitStore])
```

- [ ] **Step 3.4: Make `teardown` conservative-confirm any pending tentative**

Replace the existing `teardown` (lines 236-255) with:

```ts
  const teardown = useCallback(async (restoreSid: string | null) => {
    try { audioCapture.stopContinuous() } catch { /* not active */ }
    clearPendingBarge()
    // Tentative barges are torn down as if confirmed (conservative): when
    // the user leaves conv-mode or the session is disposed, we do NOT want
    // a muted audio source sitting around waiting for an STT result that
    // may never land.
    tentativeRef.current = false
    bargeIdRef.current += 1
    cancelStreamingAutoRead()
    audioPlayback.stopAll()

    const prev = useConversationModeStore.getState().previousReasoningOverride
    if (restoreSid) {
      try {
        await chatApi.updateSessionReasoning(restoreSid, prev)
      } catch (err) {
        console.error('[ConversationMode] Failed to restore reasoning override:', err)
      }
    }
    useChatStore.getState().setReasoningOverride(prev)

    heldAudioRef.current = []
  }, [clearPendingBarge])
```

- [ ] **Step 3.5: Update the `handleSpeechStart` doc comment**

The behaviour comment on `handleSpeechStart` (lines 168-176) is now out of date. Replace those jsdoc lines with:

```ts
  /**
   * VAD speech-start handler. If the user speaks while the LLM is thinking
   * or a reply is playing, this schedules a Tentative Barge after
   * BARGE_DELAY_MS (the 150 ms misfire window). On fire, `executeBarge`
   * mutes playback without tearing down synthesis or the LLM stream; the
   * tear-down only happens once STT confirms a non-empty transcript (see
   * `transcribeAndSend`). If Silero retracts via `onVADMisfire` inside the
   * window, the pending barge is cancelled and nothing is muted.
   */
```

- [ ] **Step 3.6: Run the whole voice test suite to ensure nothing else broke**

Run: `cd frontend && pnpm vitest run src/features/voice`

Expected: all existing tests still pass. (No new test on the hook itself at this point — it's too side-effect heavy; the pure decider in Task 2 is where the logic is covered.)

- [ ] **Step 3.7: Type-check the whole frontend**

Run: `cd frontend && pnpm tsc --noEmit`

Expected: no errors.

- [ ] **Step 3.8: Commit**

```bash
git add frontend/src/features/voice/hooks/useConversationMode.ts
git commit -m "Wire tentative-barge flow into conversation mode hook"
```

---

## Task 4: Manual regression and acceptance testing

This is the verification task. No code changes. Actually listen to each scenario; do not just read the logs.

**Files:** none

- [ ] **Step 4.1: Build the frontend**

Run: `cd frontend && pnpm run build`

Expected: clean build, no TypeScript errors.

- [ ] **Step 4.2: Start the dev stack**

Run: `docker compose up -d` (if not already running), then `cd frontend && pnpm dev`.

Open the app in a browser, log in, enter a chat session with a persona that has voice enabled, and activate Conversational Mode.

- [ ] **Step 4.3: Regression scenarios — each must behave as listed**

Trigger the scenarios below and verify the observed behaviour matches the expected column. Mark each row pass/fail in the PR description.

| # | Scenario | Expected |
|---|----------|----------|
| 1 | Ask the assistant a long-ish question, then **cough once** while it's replying | Audio goes silent for ~0.5–1 s, then the assistant's sentence restarts from its beginning and the reply continues |
| 2 | Ask a question, then **type on the keyboard** for 2 s during the reply | Same as #1 — sentence restarts after the noise ends and STT returns empty |
| 3 | Ask a question, then **speak an actual interrupting sentence** during the reply | Audio goes silent immediately; the new user sentence is transcribed and sent; the original assistant reply is abandoned |
| 4 | Ask a question; during the reply, cough, then before playback fully resumes, cough again | Audio stays muted during both coughs; resumes exactly once after the second STT confirms empty; no stuck mute |
| 5 | Ask a question; during the reply, speak for 15–20 s continuously (longer than typical) | Playback stays muted the whole time; after you stop, STT runs and confirms — reply is aborted and the long utterance is sent |
| 6 | Ask a question; during the reply, cough; STT returns empty and playback resumes; immediately cough again | Second cough triggers a fresh tentative barge; first cough's mute anchor does not interfere; playback resumes correctly after the second |
| 7 | Start a long assistant reply; cough during it; before STT completes, **leave conversational mode** via the UI toggle | Playback tears down cleanly; no lingering muted audio; no `onFinished` spam in the console |
| 8 | Start a reply; cough; STT returns empty; the reply finishes normally | Full reply is heard in the correct order with no duplicated or skipped sentences |
| 9 | Start a reply with modulation (non-1.0 speed or non-0 pitch); cough mid-sentence | Playback resumes with the same speed/pitch as before (the re-queued entry still carries the segment's modulation params) |

- [ ] **Step 4.4: Check the browser console**

Expected: no new warnings or errors during scenarios 1–9 beyond the pre-existing baseline.

- [ ] **Step 4.5: Commit the plan execution record**

No code changes in this step; just confirm all scenario results in the PR description.

---

## Merge

Once Task 4 passes end-to-end, merge to `master` per project policy (`CLAUDE.md` → "Please always merge to master after implementation"). Suggested merge commit message:

```
Implement Tentative Barge for live speech mode

Two-stage commit for barge-in: mute audio on VAD detection but defer
teardown of synthesis / LLM / queue until STT returns a non-empty
transcript. Non-speech noise during playback (coughs, typing, room
noise) no longer aborts the assistant's reply.

See devdocs/superpowers/specs/2026-04-18-tentative-barge-design.md
```
