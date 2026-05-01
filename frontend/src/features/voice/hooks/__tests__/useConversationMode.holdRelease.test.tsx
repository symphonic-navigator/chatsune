import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CapturedAudio } from '../../types'

// These mocks must be set up BEFORE the hook is imported. We capture the
// callbacks passed into audioCapture.startContinuous so that each test can
// synthesise VAD speech-start / speech-end / misfire events at will.
interface CapturedCallbacks {
  onSpeechStart: () => void
  onSpeechEnd: (audio: CapturedAudio) => void
  onVolumeChange: (level: number) => void
  onMisfire?: () => void
}
let captured: CapturedCallbacks | null = null

vi.mock('../../infrastructure/audioCapture', () => ({
  audioCapture: {
    startContinuous: vi.fn(async (cbs: CapturedCallbacks, _options?: unknown) => {
      captured = cbs
    }),
    stopContinuous: vi.fn(() => {
      captured = null
    }),
    // The hook calls this to decide whether to start its own MediaRecorder.
    // Returning null forces the Tier-3 WAV fallback path, which is what the
    // hold-release behaviour tests assert against (the PCM length equality
    // checks only hold when we build the Tier-3 WAV from the merged PCM).
    getMediaStream: vi.fn(() => null),
  },
}))

// Build a CapturedAudio with the given PCM; blob/mimeType reflect the
// Tier-3 WAV fallback because the tests do not exercise MediaRecorder.
function captureFromPcm(pcm: Float32Array): CapturedAudio {
  return {
    pcm,
    blob: new Blob([], { type: 'audio/wav' }),
    mimeType: 'audio/wav',
    sampleRate: 16_000,
    durationMs: (pcm.length / 16_000) * 1000,
  }
}

vi.mock('../../infrastructure/audioPlayback', () => ({
  audioPlayback: {
    mute: vi.fn(),
    resumeFromMute: vi.fn(),
    isPlaying: vi.fn(() => false),
    isMuted: vi.fn(() => false),
  },
}))

vi.mock('../../pipeline/voicePipeline', () => ({
  voicePipeline: {
    stopRecording: vi.fn(),
  },
}))

vi.mock('../../../chat/responseTaskGroup', () => ({
  getActiveGroup: () => ({ pause: vi.fn(), resume: vi.fn(), cancel: vi.fn() }),
}))

vi.mock('../../components/ReadAloudButton', () => ({
  setActiveReader: vi.fn(),
}))

const transcribeMock = vi.fn<(audio: CapturedAudio) => Promise<{ text: string }>>()
vi.mock('../../engines/resolver', () => ({
  resolveSTTEngine: () => ({
    id: 'fake-stt',
    name: 'Fake',
    modelSize: 0,
    languages: ['en'],
    init: vi.fn(),
    dispose: vi.fn(),
    isReady: () => true,
    transcribe: transcribeMock,
  }),
  resolveTTSEngine: () => undefined,
}))

vi.mock('../../../../core/api/chat', () => ({
  chatApi: {
    updateSessionReasoning: vi.fn(async () => ({})),
  },
}))

// Import AFTER mocks are declared.
import { useConversationMode } from '../useConversationMode'
import { useConversationModeStore } from '../../stores/conversationModeStore'
import { useChatStore } from '../../../../core/store/chatStore'
import { useNotificationStore } from '../../../../core/store/notificationStore'
import { registerCommand, unregisterCommand } from '../../../voice-commands'
import type { CommandSpec } from '../../../voice-commands'

function resetConvModeStore() {
  useConversationModeStore.setState({
    active: false,
    isHolding: false,
    previousReasoningOverride: null,
    currentBargeState: null,
    sttInFlight: false,
    vadActive: false,
  })
}

function resetChatStore() {
  useChatStore.setState({
    isStreaming: false,
    isWaitingForResponse: false,
    reasoningOverride: null,
  })
}

function resetNotifications() {
  useNotificationStore.setState({ notifications: [] })
}

async function flushMicrotasks() {
  // Resolve any pending microtasks (startContinuous is async, so the
  // callback-capture happens one microtask after enter()).
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

describe('useConversationMode — hold-release VAD-state gating', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    captured = null
    transcribeMock.mockReset()
    transcribeMock.mockResolvedValue({ text: 'hello world' })
    resetConvModeStore()
    resetChatStore()
    resetNotifications()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('merges late VAD speech-end (arriving after hold release) with the buffered chunk into one transcription', async () => {
    renderHook(() => useConversationMode({
      sessionId: 's1',
      available: true,
      buildAndRegisterGroup: vi.fn(() => 'new-group'),
      sendChatMessage: vi.fn(),
    }))

    // Enter conv-mode and let startContinuous resolve.
    await act(async () => {
      useConversationModeStore.getState().enter()
      await flushMicrotasks()
    })
    expect(captured).not.toBeNull()

    // User starts speaking. Advance past the 150 ms barge window so speech
    // is "accepted". VAD is now actively tracking an utterance.
    act(() => { captured!.onSpeechStart() })
    await act(async () => { vi.advanceTimersByTime(200) })

    // User presses and holds the "keep talking" button.
    act(() => { useConversationModeStore.getState().setHolding(true) })

    // First utterance ends while holding — audio is buffered, nothing sent.
    // This speech-end marks VAD as idle again.
    const audio1 = new Float32Array(16_000) // 1 s @ 16 kHz
    audio1.fill(0.1)
    act(() => { captured!.onSpeechEnd(captureFromPcm(audio1)) })
    expect(transcribeMock).not.toHaveBeenCalled()

    // User resumes speaking while still holding — VAD active again.
    act(() => { captured!.onSpeechStart() })
    await act(async () => { vi.advanceTimersByTime(200) })

    // User releases the hold WHILE VAD is still tracking the second utterance.
    // The release effect must now wait for the next speech-end rather than
    // dispatching the buffered chunk immediately.
    act(() => { useConversationModeStore.getState().setHolding(false) })

    // ~100 ms later (still well under the old 500 ms grace window) Silero
    // finally fires the redemption speech-end with the trailing chunk.
    await act(async () => { vi.advanceTimersByTime(100) })
    const audio2 = new Float32Array(8_000) // 0.5 s @ 16 kHz
    audio2.fill(0.2)
    act(() => { captured!.onSpeechEnd(captureFromPcm(audio2)) })

    // Drain any remaining timers so nothing fires after assertions.
    await act(async () => { vi.advanceTimersByTime(1_000) })
    await act(async () => { await flushMicrotasks() })

    // Exactly ONE STT call, with the concatenated audio length.
    expect(transcribeMock).toHaveBeenCalledTimes(1)
    const sent = transcribeMock.mock.calls[0][0]
    expect(sent.pcm.length).toBe(audio1.length + audio2.length)
  })

  it('dispatches buffered audio immediately when VAD is idle at release time', async () => {
    renderHook(() => useConversationMode({
      sessionId: 's1',
      available: true,
      buildAndRegisterGroup: vi.fn(() => 'new-group'),
      sendChatMessage: vi.fn(),
    }))

    await act(async () => {
      useConversationModeStore.getState().enter()
      await flushMicrotasks()
    })
    expect(captured).not.toBeNull()

    act(() => { captured!.onSpeechStart() })
    await act(async () => { vi.advanceTimersByTime(200) })

    act(() => { useConversationModeStore.getState().setHolding(true) })

    const audio1 = new Float32Array(12_000)
    audio1.fill(0.3)
    // speech-end BEFORE release → VAD is idle at release time.
    act(() => { captured!.onSpeechEnd(captureFromPcm(audio1)) })
    expect(transcribeMock).not.toHaveBeenCalled()

    // Release during inter-utterance silence. VAD is idle, so we dispatch
    // synchronously — no timer advance needed.
    act(() => { useConversationModeStore.getState().setHolding(false) })
    await act(async () => { await flushMicrotasks() })

    expect(transcribeMock).toHaveBeenCalledTimes(1)
    const sent = transcribeMock.mock.calls[0][0]
    expect(sent.pcm.length).toBe(audio1.length)
  })

  it('release with VAD idle (all speech-ends already fired) dispatches synchronously, no timer', async () => {
    renderHook(() => useConversationMode({
      sessionId: 's1',
      available: true,
      buildAndRegisterGroup: vi.fn(() => 'new-group'),
      sendChatMessage: vi.fn(),
    }))

    await act(async () => {
      useConversationModeStore.getState().enter()
      await flushMicrotasks()
    })
    expect(captured).not.toBeNull()

    // Speech-start then speech-end while holding; VAD returns to idle.
    act(() => { useConversationModeStore.getState().setHolding(true) })
    act(() => { captured!.onSpeechStart() })
    await act(async () => { vi.advanceTimersByTime(200) })
    const audio = new Float32Array(5_000)
    audio.fill(0.4)
    act(() => { captured!.onSpeechEnd(captureFromPcm(audio)) })

    // Release → immediate dispatch. No timers advanced.
    act(() => { useConversationModeStore.getState().setHolding(false) })
    await act(async () => { await flushMicrotasks() })

    expect(transcribeMock).toHaveBeenCalledTimes(1)
    expect(transcribeMock.mock.calls[0][0].pcm.length).toBe(audio.length)
  })

  it('release mid-utterance merges with late speech-end beyond the original 500 ms window', async () => {
    renderHook(() => useConversationMode({
      sessionId: 's1',
      available: true,
      buildAndRegisterGroup: vi.fn(() => 'new-group'),
      sendChatMessage: vi.fn(),
    }))

    await act(async () => {
      useConversationModeStore.getState().enter()
      await flushMicrotasks()
    })
    expect(captured).not.toBeNull()

    // Four held speech-end events buffered.
    act(() => { useConversationModeStore.getState().setHolding(true) })

    const seg1 = new Float32Array(4_000); seg1.fill(0.1)
    const seg2 = new Float32Array(4_000); seg2.fill(0.2)
    const seg3 = new Float32Array(4_000); seg3.fill(0.3)
    const seg4 = new Float32Array(4_000); seg4.fill(0.4)

    for (const seg of [seg1, seg2, seg3, seg4]) {
      act(() => { captured!.onSpeechStart() })
      await act(async () => { vi.advanceTimersByTime(200) })
      act(() => { captured!.onSpeechEnd(captureFromPcm(seg)) })
    }
    expect(transcribeMock).not.toHaveBeenCalled()

    // User resumes speaking — VAD active again.
    act(() => { captured!.onSpeechStart() })
    await act(async () => { vi.advanceTimersByTime(200) })

    // User releases mid-utterance.
    act(() => { useConversationModeStore.getState().setHolding(false) })

    // Advance 800 ms — longer than old 500 ms grace, shorter than 3 s safety.
    await act(async () => { vi.advanceTimersByTime(800) })
    // No dispatch yet: we're waiting for the speech-end.
    expect(transcribeMock).not.toHaveBeenCalled()

    // Final chunk finally arrives.
    const seg5 = new Float32Array(4_000); seg5.fill(0.5)
    act(() => { captured!.onSpeechEnd(captureFromPcm(seg5)) })
    await act(async () => { await flushMicrotasks() })

    expect(transcribeMock).toHaveBeenCalledTimes(1)
    const sent = transcribeMock.mock.calls[0][0]
    expect(sent.pcm.length).toBe(seg1.length + seg2.length + seg3.length + seg4.length + seg5.length)
  })

  it('safety fallback dispatches buffer if no speech-end arrives within 3 s', async () => {
    renderHook(() => useConversationMode({
      sessionId: 's1',
      available: true,
      buildAndRegisterGroup: vi.fn(() => 'new-group'),
      sendChatMessage: vi.fn(),
    }))

    await act(async () => {
      useConversationModeStore.getState().enter()
      await flushMicrotasks()
    })
    expect(captured).not.toBeNull()

    act(() => { useConversationModeStore.getState().setHolding(true) })

    // One buffered speech-end.
    act(() => { captured!.onSpeechStart() })
    await act(async () => { vi.advanceTimersByTime(200) })
    const audio1 = new Float32Array(6_000); audio1.fill(0.5)
    act(() => { captured!.onSpeechEnd(captureFromPcm(audio1)) })

    // User resumes speaking — VAD active again; no speech-end will arrive.
    act(() => { captured!.onSpeechStart() })
    await act(async () => { vi.advanceTimersByTime(200) })

    // Release while VAD is active.
    act(() => { useConversationModeStore.getState().setHolding(false) })

    // Advance past safety fallback (3 s).
    await act(async () => { vi.advanceTimersByTime(3_100) })
    await act(async () => { await flushMicrotasks() })

    expect(transcribeMock).toHaveBeenCalledTimes(1)
    const sent = transcribeMock.mock.calls[0][0]
    expect(sent.pcm.length).toBe(audio1.length)
  })
})

// ---------------------------------------------------------------------------
// §15.2 — Voice-command dispatch path integration test
// ---------------------------------------------------------------------------
// Exercises the real tryDispatchCommand wiring in useConversationMode lines
// 344-357: when the STT result matches a registered trigger, controller.commit
// (and therefore sendChatMessage) must NOT be called; a toast notification
// must appear via respondToUser → useNotificationStore.

describe('useConversationMode — voice-command dispatch', () => {
  // Register a minimal test command whose trigger is unlikely to collide with
  // any real command. The handler returns a deterministic displayText so the
  // notification assertion can be exact.
  const TEST_TRIGGER = 'testfoo'
  const fooHandler = vi.fn(async (body: string) => ({
    level: 'info' as const,
    displayText: `foo body: '${body}'`,
  }))
  const fooCommand: CommandSpec = {
    trigger: TEST_TRIGGER,
    onTriggerWhilePlaying: 'resume',
    source: 'core',
    execute: fooHandler,
  }

  beforeEach(() => {
    vi.useFakeTimers()
    captured = null
    resetConvModeStore()
    resetChatStore()
    resetNotifications()
    transcribeMock.mockReset()
    fooHandler.mockClear()
    registerCommand(fooCommand)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
    unregisterCommand(TEST_TRIGGER)
  })

  it('STT result matching a registered trigger does not call sendChatMessage; a notification is emitted', async () => {
    const sendChatMessage = vi.fn()
    // "testfoo ping" → normalise → ['testfoo', 'ping'] → trigger='testfoo', body='ping'.
    transcribeMock.mockResolvedValue({ text: 'testfoo ping' })

    renderHook(() => useConversationMode({
      sessionId: 's1',
      available: true,
      buildAndRegisterGroup: vi.fn(() => 'new-group'),
      sendChatMessage,
    }))

    await act(async () => {
      useConversationModeStore.getState().enter()
      await flushMicrotasks()
    })
    expect(captured).not.toBeNull()

    // Synthesise a speech-start → speech-end cycle (same pattern as the
    // existing hold-release tests: advance 200 ms past the 150 ms barge
    // window so the barge is accepted, then fire speech-end with a small PCM
    // buffer to trigger transcription).
    act(() => { captured!.onSpeechStart() })
    await act(async () => { vi.advanceTimersByTime(200) })
    const pcm = new Float32Array(16_000) // 1 second of silence at 16 kHz
    act(() => { captured!.onSpeechEnd(captureFromPcm(pcm)) })
    await act(async () => { await flushMicrotasks() })

    // STT must have been called exactly once.
    expect(transcribeMock).toHaveBeenCalledTimes(1)

    // The command handler must have been invoked with just the body ('ping').
    expect(fooHandler).toHaveBeenCalledWith('ping')

    // The dispatch path must NOT have called sendChatMessage.
    expect(sendChatMessage).not.toHaveBeenCalled()

    // respondToUser must have pushed exactly one notification with the
    // handler's displayText.
    expect(useNotificationStore.getState().notifications).toHaveLength(1)
    expect(useNotificationStore.getState().notifications[0].message).toBe(`foo body: 'ping'`)
  })
})
