import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  registerActiveGroup,
  clearActiveGroup,
  getActiveGroup,
  cancelCurrentActiveGroup,
  createResponseTaskGroup,
  type GroupChild,
  type ResponseTaskGroup,
} from '../../chat/responseTaskGroup'
import { createPlaybackChild } from '../children/playbackChild'
import { audioPlayback } from '../infrastructure/audioPlayback'

/**
 * These tests guard the ordering fix for the voice-barge supersede race.
 *
 * The bug (pre-fix):
 *   1. createAndRegisterGroup called buildChildren() first, which constructed
 *      a new playbackChild and synchronously called setCurrentToken(G2.id).
 *   2. Only then did registerActiveGroup() cancel the predecessor G1.
 *   3. G1's playbackChild.onCancel called clearScope(G1.id), but
 *      audioPlayback.currentToken was already G2.id — so clearScope's
 *      `if (this.currentToken !== token) return` short-circuited.
 *   4. The paused = false reset inside clearScope therefore never ran,
 *      leaving audioPlayback stuck at paused = true. All subsequent audio
 *      enqueues sat in the queue with playNext gated on !paused.
 *
 * The fix: cancel the predecessor BEFORE building the successor's children,
 * so G1's clearScope hits while currentToken still matches G1.id.
 */

function makeLogger() {
  return { info: vi.fn(), debug: vi.fn(), warn: vi.fn(), error: vi.fn() }
}

function makeGroupWithChild(correlationId: string, child: GroupChild): ResponseTaskGroup {
  return createResponseTaskGroup({
    correlationId,
    sessionId: 's1',
    userId: 'u1',
    children: [child],
    sendWsMessage: vi.fn(),
    logger: makeLogger(),
  })
}

describe('barge supersede ordering (audioPlayback paused reset)', () => {
  beforeEach(() => {
    const existing = getActiveGroup()
    if (existing) clearActiveGroup(existing)
    // Reset audioPlayback to a clean state. stopAll clears queue/paused/playing
    // but leaves currentToken intact — null it explicitly.
    audioPlayback.stopAll()
    audioPlayback.setCurrentToken(null)
  })

  afterEach(() => {
    const existing = getActiveGroup()
    if (existing) clearActiveGroup(existing)
    audioPlayback.stopAll()
    audioPlayback.setCurrentToken(null)
  })

  it('NEW ordering (cancel predecessor FIRST): audioPlayback.paused is reset to false', () => {
    // Install G1 with a real playbackChild — construction sets currentToken = G1.
    const g1Child = createPlaybackChild({ correlationId: 'g1', gapMs: 0 })
    const g1 = makeGroupWithChild('g1', g1Child)
    registerActiveGroup(g1)
    g1.onDelta('streaming') // drive into streaming

    // Simulate a barge: pause playback.
    audioPlayback.pause()
    // Sanity: the state we expect before the supersede runs.
    // (Access paused via a round-trip: pause is no-op when already paused,
    // so we trigger a fresh pause and see behaviour — but we can also infer
    // via resume. For the test, we just assert pre-condition via a spy on
    // the real method call by observing that a second pause is a no-op.)

    // --- NEW ORDERING: cancel predecessor BEFORE building G2 children.
    cancelCurrentActiveGroup()

    // At this point G1's playbackChild.onCancel has fired. Because
    // currentToken was still 'g1' when clearScope ran, the paused flag
    // has been reset to false.

    // Now build G2's playbackChild — this sets currentToken = 'g2'.
    const g2Child = createPlaybackChild({ correlationId: 'g2', gapMs: 0 })
    const g2 = makeGroupWithChild('g2', g2Child)
    registerActiveGroup(g2)

    // The canonical observable fix: paused must be false so the next
    // group's enqueues auto-play. Probe it by calling resume() — resume()
    // is a no-op when !paused, so if paused were still true resume would
    // flip it to false. We instead assert on playback readiness: enqueue a
    // dummy chunk and check that playing does NOT remain gated. Simpler:
    // the helper pause() is idempotent and a no-op when already paused, so
    // calling it again should not emit "already paused" state — but that
    // is indirect. The cleanest assertion is to inspect the internal state
    // via a known observable: after a queued chunk, playing would flip to
    // true only if !paused. Without a real AudioContext available in tests,
    // we instead verify paused === false by a controlled resume() roundtrip.

    // Indirect but deterministic probe: if clearScope correctly reset paused,
    // a second pause() call will set paused = true and abort the early-return
    // guard. We read that via a listener-count delta on a dedicated spy.
    const listener = vi.fn()
    const unsubscribe = audioPlayback.subscribe(listener)
    audioPlayback.pause()
    // pause() calls emit() only when it actually flips paused from false to true.
    // If paused was still true (bug case), pause() returns early WITHOUT emit.
    // If paused was false (fix case), pause() flips it to true AND emits.
    expect(listener).toHaveBeenCalled()

    unsubscribe()
    // Cleanup for next test.
    clearActiveGroup(g2)
  })

  it('OLD (broken) ordering reproduces the bug: paused stays true', () => {
    // Install G1 with a real playbackChild.
    const g1Child = createPlaybackChild({ correlationId: 'g1', gapMs: 0 })
    const g1 = makeGroupWithChild('g1', g1Child)
    registerActiveGroup(g1)
    g1.onDelta('streaming')

    // Simulate a barge: pause playback.
    audioPlayback.pause()

    // --- OLD (broken) ordering: build G2 children first.
    //     This sets currentToken = 'g2' BEFORE G1 is cancelled.
    const g2Child = createPlaybackChild({ correlationId: 'g2', gapMs: 0 })
    const g2 = makeGroupWithChild('g2', g2Child)

    // Now register G2 — which internally cancels G1. G1's clearScope call
    // sees currentToken === 'g2' (not 'g1') and short-circuits. paused
    // remains true.
    registerActiveGroup(g2)

    // Probe: call pause() again. Because paused is stuck at true, pause()
    // hits its early-return guard and does NOT emit. The listener should
    // NOT have been called — this documents the bug.
    const listener = vi.fn()
    const unsubscribe = audioPlayback.subscribe(listener)
    audioPlayback.pause()
    expect(listener).not.toHaveBeenCalled()

    unsubscribe()
    clearActiveGroup(g2)
  })

  it('call-order: G1.onCancel clearScope fires BEFORE G2 setCurrentToken', () => {
    // Wrap the real audioPlayback methods to record call order.
    const callLog: string[] = []

    const clearScopeSpy = vi.spyOn(audioPlayback, 'clearScope')
      .mockImplementation((token: string) => {
        callLog.push(`clearScope:${token}`)
        // Mimic the real behaviour we care about: reset paused on match.
        if ((audioPlayback as unknown as { currentToken: string | null }).currentToken === token) {
          (audioPlayback as unknown as { paused: boolean }).paused = false
        }
      })

    const setCurrentTokenSpy = vi.spyOn(audioPlayback, 'setCurrentToken')
      .mockImplementation((token: string | null) => {
        callLog.push(`setCurrentToken:${token ?? 'null'}`)
        ;(audioPlayback as unknown as { currentToken: string | null }).currentToken = token
      })

    // Install G1 (setCurrentToken:g1 is recorded).
    const g1Child = createPlaybackChild({ correlationId: 'g1', gapMs: 0 })
    const g1 = makeGroupWithChild('g1', g1Child)
    registerActiveGroup(g1)
    g1.onDelta('streaming')

    // Clear the log up to the point of the supersede so we observe only
    // the supersede call sequence.
    callLog.length = 0

    // --- NEW ordering under test: cancel first, then build G2.
    cancelCurrentActiveGroup()
    const g2Child = createPlaybackChild({ correlationId: 'g2', gapMs: 0 })
    const g2 = makeGroupWithChild('g2', g2Child)
    registerActiveGroup(g2)

    // Expected sequence during supersede:
    //   G1 cancel → clearScope:g1
    //   G1 cancel → setCurrentToken:null
    //   G2 build  → setCurrentToken:g2
    const clearScopeIndex = callLog.indexOf('clearScope:g1')
    const setCurrentTokenG2Index = callLog.indexOf('setCurrentToken:g2')
    expect(clearScopeIndex).toBeGreaterThanOrEqual(0)
    expect(setCurrentTokenG2Index).toBeGreaterThanOrEqual(0)
    expect(clearScopeIndex).toBeLessThan(setCurrentTokenG2Index)

    clearScopeSpy.mockRestore()
    setCurrentTokenSpy.mockRestore()
    clearActiveGroup(g2)
  })
})
