import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CapturedAudio } from '../../types'

// Mocks mirror the holdRelease test file: capture the VAD callbacks and
// pass through a real audioPlayback so spies on its methods are observable.
interface CapturedCallbacks {
  onSpeechStart: () => void
  onSpeechEnd: (audio: CapturedAudio) => void
  onVolumeChange: (level: number) => void
  onMisfire?: () => void
}
let captured: CapturedCallbacks | null = null

vi.mock('../../infrastructure/audioCapture', () => ({
  audioCapture: {
    startContinuous: vi.fn(async (cbs: CapturedCallbacks) => {
      captured = cbs
    }),
    stopContinuous: vi.fn(() => {
      captured = null
    }),
    getMediaStream: vi.fn(() => null),
  },
}))

function captureFromPcm(pcm: Float32Array): CapturedAudio {
  return {
    pcm,
    blob: new Blob([], { type: 'audio/wav' }),
    mimeType: 'audio/wav',
    sampleRate: 16_000,
    durationMs: (pcm.length / 16_000) * 1000,
  }
}

// NOTE: we intentionally do NOT mock the audioPlayback module — the spec
// requires spying on the real methods via vi.spyOn so the real discardMuted
// implementation is exercised where reachable.

vi.mock('../../pipeline/voicePipeline', () => ({
  voicePipeline: {
    stopRecording: vi.fn(),
  },
}))

vi.mock('../../pipeline/streamingAutoReadControl', () => ({
  cancelStreamingAutoRead: vi.fn(),
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

import { useConversationMode } from '../useConversationMode'
import { useConversationModeStore } from '../../stores/conversationModeStore'
import { useChatStore } from '../../../../core/store/chatStore'
import { useNotificationStore } from '../../../../core/store/notificationStore'
import { audioPlayback } from '../../infrastructure/audioPlayback'

function resetConvModeStore() {
  useConversationModeStore.setState({
    active: false,
    phase: 'idle',
    isHolding: false,
    previousReasoningOverride: null,
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
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

/**
 * Drive one full barge cycle (speech-start, past misfire window, speech-end)
 * with the given STT transcript. The returned promise settles after the STT
 * result has been handled.
 */
async function driveBargeCycle(transcript: string): Promise<void> {
  transcribeMock.mockResolvedValueOnce({ text: transcript })
  // executeBarge only mutes + sets tentativeRef when phase is thinking or
  // speaking. Force it before firing speech-start so the deferred barge
  // picks up the right phase.
  act(() => { useConversationModeStore.getState().setPhase('speaking') })
  act(() => { captured!.onSpeechStart() })
  await act(async () => { vi.advanceTimersByTime(200) })
  const audio = new Float32Array(4_000)
  audio.fill(0.1)
  act(() => { captured!.onSpeechEnd(captureFromPcm(audio)) })
  // STT is async — drain microtasks so the outcome branch runs.
  await act(async () => { await flushMicrotasks() })
}

describe('useConversationMode — tentative-barge safety cap', () => {
  let muteSpy: ReturnType<typeof vi.spyOn>
  let resumeSpy: ReturnType<typeof vi.spyOn>
  let discardSpy: ReturnType<typeof vi.spyOn>
  let isPlayingSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    vi.useFakeTimers()
    captured = null
    transcribeMock.mockReset()
    resetConvModeStore()
    resetChatStore()
    resetNotifications()
    // Stub only the methods the hook touches; let the spies observe calls
    // without running the real audio context.
    muteSpy = vi.spyOn(audioPlayback, 'mute').mockImplementation(() => {})
    resumeSpy = vi.spyOn(audioPlayback, 'resumeFromMute').mockImplementation(() => {})
    discardSpy = vi.spyOn(audioPlayback, 'discardMuted').mockImplementation(() => {})
    isPlayingSpy = vi.spyOn(audioPlayback, 'isPlaying').mockReturnValue(false)
  })

  afterEach(() => {
    vi.useRealTimers()
    muteSpy.mockRestore()
    resumeSpy.mockRestore()
    discardSpy.mockRestore()
    isPlayingSpy.mockRestore()
    vi.clearAllMocks()
  })

  it('after 3 consecutive resume outcomes, discardMuted is called instead of resumeFromMute', async () => {
    renderHook(() => useConversationMode({ sessionId: 's1', available: true, onSend: vi.fn() }))
    await act(async () => {
      useConversationModeStore.getState().enter()
      await flushMicrotasks()
    })
    expect(captured).not.toBeNull()

    // Three resume outcomes in a row (empty transcripts → 'resume').
    await driveBargeCycle('')
    await driveBargeCycle('')
    await driveBargeCycle('')

    expect(resumeSpy).toHaveBeenCalledTimes(2)
    expect(discardSpy).toHaveBeenCalledTimes(1)
  })

  it('a confirm outcome resets the counter', async () => {
    const onSend = vi.fn()
    renderHook(() => useConversationMode({ sessionId: 's1', available: true, onSend }))
    await act(async () => {
      useConversationModeStore.getState().enter()
      await flushMicrotasks()
    })
    expect(captured).not.toBeNull()

    // 2 resumes, 1 confirm, then 1 more resume — should still resume (not discard).
    await driveBargeCycle('')
    await driveBargeCycle('')
    await driveBargeCycle('hello there')
    await driveBargeCycle('')

    expect(onSend).toHaveBeenCalledTimes(1)
    expect(discardSpy).not.toHaveBeenCalled()
    // Resumes: two before the confirm, one after → three total.
    expect(resumeSpy).toHaveBeenCalledTimes(3)
  })

  it('RESUME_RESET_MS elapsing resets the counter', async () => {
    renderHook(() => useConversationMode({ sessionId: 's1', available: true, onSend: vi.fn() }))
    await act(async () => {
      useConversationModeStore.getState().enter()
      await flushMicrotasks()
    })
    expect(captured).not.toBeNull()

    // 1 resume.
    await driveBargeCycle('')
    expect(resumeSpy).toHaveBeenCalledTimes(1)

    // Advance past the 5 s reset window.
    await act(async () => { vi.advanceTimersByTime(5_100) })

    // Two more resumes in quick succession — should still resume, not discard.
    await driveBargeCycle('')
    await driveBargeCycle('')

    expect(discardSpy).not.toHaveBeenCalled()
    expect(resumeSpy).toHaveBeenCalledTimes(3)
  })
})
