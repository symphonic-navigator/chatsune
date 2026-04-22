/**
 * Barge controller — owns the in-flight voice-barge attempt.
 *
 * See devdocs/voice-barge-structural-redesign.md §2 and §3. Replaces the
 * parallel tentativeRef/bargeIdRef state that lived in useConversationMode
 * with a single object whose lifetime matches one user-speech attempt.
 *
 * Identity is by reference, not numeric id: the STT promise holds a direct
 * reference to its Barge, so staleness is `barge !== controller.current`.
 * The `id` field is a UUID purely for log correlation.
 *
 * Every state transition goes through this controller. No other module may
 * mutate `Barge.state`.
 */

import { getActiveGroup } from '../chat/responseTaskGroup'

export type BargeState = 'pending-stt' | 'confirmed' | 'resumed' | 'stale' | 'abandoned'

export interface Barge {
  readonly id: string
  readonly pausedGroupId: string | null
  readonly createdAt: number
  state: BargeState
}

export interface BargeLogger {
  info(...args: unknown[]): void
  debug(...args: unknown[]): void
  warn(...args: unknown[]): void
  error(...args: unknown[]): void
}

export interface BargeControllerDeps {
  /** Build and register a new ResponseTaskGroup for the voice-send transcript.
   *  Must call registerActiveGroup internally (mirrors ChatView.createAndRegisterGroup
   *  in frontend/src/features/chat/ChatView.tsx:499). Returns the new Group's id. */
  buildAndRegisterGroup: (correlationId: string, transcript: string) => string

  /** Send chat.send over the WebSocket with the given correlation id + content. */
  sendChatMessage: (correlationId: string, content: string) => void

  logger: BargeLogger
}

export interface BargeController {
  start(): Barge
  commit(barge: Barge, transcript: string): void
  resume(barge: Barge): void
  stale(barge: Barge): void
  abandonAll(): void
  readonly current: Barge | null
}

function hash8(id: string): string {
  return id.slice(0, 8)
}

export function createBargeController(deps: BargeControllerDeps): BargeController {
  const { buildAndRegisterGroup, sendChatMessage, logger } = deps
  let currentBarge: Barge | null = null

  function prefix(barge: Barge): string {
    return `[barge ${hash8(barge.id)}]`
  }

  return {
    get current() {
      return currentBarge
    },

    start(): Barge {
      const active = getActiveGroup()
      const barge: Barge = {
        id: crypto.randomUUID(),
        pausedGroupId: active?.id ?? null,
        createdAt: Date.now(),
        state: 'pending-stt',
      }
      currentBarge = barge
      logger.info(
        `${prefix(barge)} start (pausedGroupId=${barge.pausedGroupId ?? 'none'})`,
      )
      // Group.pause() is idempotent and no-ops outside streaming/tailing, so
      // calling it unconditionally here is safe.
      if (active) active.pause()
      return barge
    },

    commit(barge: Barge, transcript: string): void {
      if (barge !== currentBarge) {
        logger.debug(`${prefix(barge)} commit dropped (not current)`)
        return
      }
      if (barge.state !== 'pending-stt') {
        logger.debug(`${prefix(barge)} commit dropped (state=${barge.state})`)
        return
      }
      barge.state = 'confirmed'
      logger.info(`${prefix(barge)} commit (transcript.len=${transcript.length})`)

      // 1. New correlation id for the new Group.
      const newCorrelationId = crypto.randomUUID()

      // 2. Build + register the new Group. registerActiveGroup (called inside
      //    buildAndRegisterGroup) cancels the predecessor with reason
      //    'superseded' in the same synchronous block.
      buildAndRegisterGroup(newCorrelationId, transcript)

      // 3. Send chat.send for the new Group. Order is guaranteed: the
      //    predecessor's chat.cancel / chat.retract was dispatched synchronously
      //    inside the cancel('superseded') above.
      sendChatMessage(newCorrelationId, transcript)

      currentBarge = null
    },

    resume(barge: Barge): void {
      if (barge !== currentBarge) {
        logger.debug(`${prefix(barge)} resume dropped (not current)`)
        return
      }
      if (barge.state !== 'pending-stt') {
        logger.debug(`${prefix(barge)} resume dropped (state=${barge.state})`)
        return
      }
      barge.state = 'resumed'
      logger.info(`${prefix(barge)} resume`)
      const active = getActiveGroup()
      if (active && barge.pausedGroupId !== null && active.id === barge.pausedGroupId) {
        active.resume()
      }
      currentBarge = null
    },

    stale(barge: Barge): void {
      if (barge !== currentBarge) {
        logger.debug(`${prefix(barge)} stale dropped (not current)`)
        return
      }
      if (barge.state !== 'pending-stt') {
        logger.debug(`${prefix(barge)} stale dropped (state=${barge.state})`)
        return
      }
      barge.state = 'stale'
      logger.info(`${prefix(barge)} stale`)
      // Un-pause iff the Group we paused is still the active one. Mirrors
      // the current handleMisfire behaviour: misfire-after-pause must put
      // audio back even though the Barge itself is dropped.
      const active = getActiveGroup()
      if (active && barge.pausedGroupId !== null && active.id === barge.pausedGroupId) {
        active.resume()
      }
      currentBarge = null
    },

    abandonAll(): void {
      if (currentBarge) {
        currentBarge.state = 'abandoned'
        logger.info(`${prefix(currentBarge)} abandon`)
        currentBarge = null
      }
      getActiveGroup()?.cancel('teardown')
    },
  }
}
