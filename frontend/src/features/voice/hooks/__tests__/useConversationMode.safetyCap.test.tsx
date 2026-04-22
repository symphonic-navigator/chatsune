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

vi.mock('../../pipeline/voicePipeline', () => ({
  voicePipeline: {
    stopRecording: vi.fn(),
  },
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

// Provide a fake active group so the hook can call group verbs.
const fakeGroup = {
  pause: vi.fn(),
  resume: vi.fn(),
  cancel: vi.fn(),
}

vi.mock('../../../chat/responseTaskGroup', () => ({
  getActiveGroup: () => fakeGroup,
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
  // executeBarge only pauses + sets tentativeRef when phase is thinking or
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
  let isPlayingSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    vi.useFakeTimers()
    captured = null
    transcribeMock.mockReset()
    fakeGroup.pause.mockClear()
    fakeGroup.resume.mockClear()
    fakeGroup.cancel.mockClear()
    resetConvModeStore()
    resetChatStore()
    resetNotifications()
    isPlayingSpy = vi.spyOn(audioPlayback, 'isPlaying').mockReturnValue(false)
  })

  afterEach(() => {
    vi.useRealTimers()
    isPlayingSpy.mockRestore()
    vi.clearAllMocks()
  })

  it('after 3 consecutive resume outcomes, group.cancel is called instead of group.resume', async () => {
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

    // First two resume outcomes call group.resume(); third exceeds cap and calls group.cancel.
    expect(fakeGroup.resume).toHaveBeenCalledTimes(2)
    expect(fakeGroup.cancel).toHaveBeenCalledWith('barge-cancel')
  })

  it('a confirm outcome resets the counter', async () => {
    const onSend = vi.fn()
    renderHook(() => useConversationMode({ sessionId: 's1', available: true, onSend }))
    await act(async () => {
      useConversationModeStore.getState().enter()
      await flushMicrotasks()
    })
    expect(captured).not.toBeNull()

    // 2 resumes, 1 confirm, then 1 more resume — should still resume (not cancel).
    await driveBargeCycle('')
    await driveBargeCycle('')
    await driveBargeCycle('hello there')
    await driveBargeCycle('')

    expect(onSend).toHaveBeenCalledTimes(1)
    // The confirm called cancel('barge-cancel'); the 4th cycle is a resume, not a cancel.
    // cancel was called exactly once (for the confirm barge).
    const cancelCalls = fakeGroup.cancel.mock.calls.filter(([reason]) => reason !== 'teardown')
    expect(cancelCalls).toHaveLength(1)
    // Resumes: two before the confirm, one after → three total.
    expect(fakeGroup.resume).toHaveBeenCalledTimes(3)
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
    expect(fakeGroup.resume).toHaveBeenCalledTimes(1)

    // Advance past the 5 s reset window.
    await act(async () => { vi.advanceTimersByTime(5_100) })

    // Two more resumes in quick succession — should still resume, not cancel.
    await driveBargeCycle('')
    await driveBargeCycle('')

    const cancelBargeCalls = fakeGroup.cancel.mock.calls.filter(([reason]) => reason === 'barge-cancel')
    expect(cancelBargeCalls).toHaveLength(0)
    expect(fakeGroup.resume).toHaveBeenCalledTimes(3)
  })
})
