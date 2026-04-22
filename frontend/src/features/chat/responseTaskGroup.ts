/**
 * Response Task Group — one cancellable unit per assistant reply.
 *
 * See devdocs/response-task-group-architecture.md for the full design.
 * The Group owns a WS correlationId and a plugin array of children; it
 * dispatches Group-level lifecycle events (onDelta/onStreamEnd/onCancel)
 * and sends chat.cancel or chat.retract on cancel depending on state.
 *
 * This module is mode-agnostic — it knows nothing about voice, text, or
 * the chat store. Children inject that concern.
 */

export type GroupState =
  | 'before-first-delta'
  | 'streaming'
  | 'tailing'
  | 'done'
  | 'cancelled'

export type CancelReason =
  | 'barge-retract'
  | 'barge-cancel'
  | 'user-stop'
  | 'teardown'
  | 'superseded'

export interface GroupChild {
  readonly name: string
  onDelta(delta: string, token: string): void
  onStreamEnd(token: string): void | Promise<void>
  onCancel(reason: CancelReason, token: string): void
  teardown(): void | Promise<void>
  onPause?(): void
  onResume?(): void
}

export interface WsOutbound {
  type: string
  [k: string]: unknown
}

export interface GroupLogger {
  info(msg: string, ...args: unknown[]): void
  debug(msg: string, ...args: unknown[]): void
  warn(msg: string, ...args: unknown[]): void
  error(msg: string, ...args: unknown[]): void
}

export interface ResponseTaskGroupDeps {
  correlationId: string
  sessionId: string
  userId: string
  children: GroupChild[]
  sendWsMessage: (msg: WsOutbound) => void
  logger: GroupLogger
}

export interface ResponseTaskGroup {
  readonly id: string
  readonly sessionId: string
  readonly state: GroupState
  onDelta(delta: string): void
  onStreamEnd(): void
  pause(): void
  resume(): void
  cancel(reason: CancelReason): void
}

function hash8(id: string): string {
  return id.slice(0, 8)
}

export function createResponseTaskGroup(deps: ResponseTaskGroupDeps): ResponseTaskGroup {
  const { correlationId, sessionId, userId: _userId, children, sendWsMessage, logger } = deps
  const prefix = `[group ${hash8(correlationId)}]`
  let state: GroupState = 'before-first-delta'

  logger.info(
    `${prefix} created (session=${sessionId}, children=${children.map((c) => c.name).join(',')})`,
  )

  function transition(next: GroupState, reason?: CancelReason): void {
    const reasonSuffix = reason ? ` (reason=${reason})` : ''
    logger.info(`${prefix} ${state} → ${next}${reasonSuffix}`)
    state = next
    notifyActiveGroup(logger)
    if (state === 'done' || state === 'cancelled') {
      clearActiveGroup(group)
    }
  }

  const group: ResponseTaskGroup = {
    get id() { return correlationId },
    get sessionId() { return sessionId },
    get state() { return state },

    onDelta(delta: string): void {
      if (state === 'before-first-delta') transition('streaming')
      if (state !== 'streaming') {
        logger.debug(`${prefix} drop CONTENT_DELTA (state=${state})`)
        return
      }
      for (const child of children) {
        try { child.onDelta(delta, correlationId) }
        catch (err) { logger.error(`${prefix} child ${child.name} onDelta threw`, err) }
      }
    },

    onStreamEnd(): void {
      if (state !== 'streaming') {
        logger.debug(`${prefix} drop STREAM_ENDED (state=${state})`)
        return
      }
      transition('tailing')
      const drains = children.map((c) => {
        try { return Promise.resolve(c.onStreamEnd(correlationId)) }
        catch (err) {
          logger.error(`${prefix} child ${c.name} onStreamEnd threw`, err)
          return Promise.resolve()
        }
      })
      void Promise.allSettled(drains).then(() => {
        if (state !== 'tailing') return
        transition('done')
      })
    },

    pause(): void {
      if (state !== 'streaming' && state !== 'tailing') return
      logger.info(`${prefix} paused`)
      for (const child of children) child.onPause?.()
    },

    resume(): void {
      if (state !== 'streaming' && state !== 'tailing') return
      logger.info(`${prefix} resumed`)
      for (const child of children) child.onResume?.()
    },

    cancel(reason: CancelReason): void {
      if (state === 'done' || state === 'cancelled') return
      const wasBeforeDelta = state === 'before-first-delta'
      transition('cancelled', reason)
      for (const child of children) {
        try { child.onCancel(reason, correlationId) }
        catch (err) { logger.error(`${prefix} child ${child.name} onCancel threw`, err) }
      }
      sendWsMessage({
        type: wasBeforeDelta ? 'chat.retract' : 'chat.cancel',
        correlation_id: correlationId,
      })
      void Promise.allSettled(children.map(async (c) => {
        try { await c.teardown() }
        catch (err) { logger.error(`${prefix} child ${c.name} teardown threw`, err) }
      }))
    },
  }

  return group
}

// --- Registry --------------------------------------------------------------

let activeGroup: ResponseTaskGroup | null = null

export type GroupListener = (group: ResponseTaskGroup | null) => void

const listeners = new Set<GroupListener>()

export function subscribeActiveGroup(fn: GroupListener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

// Snapshot the set before iterating so a listener that synchronously
// unsubscribes itself (or another listener) during the callback does not
// break the loop. Listener errors are isolated to keep one faulty consumer
// from silencing the others.
function notifyActiveGroup(logger?: GroupLogger): void {
  const snapshot = Array.from(listeners)
  for (const fn of snapshot) {
    try {
      fn(activeGroup)
    }
    catch (err) {
      if (logger) logger.error('[group registry] listener threw', err)
      else console.error('[group registry] listener threw', err)
    }
  }
}

export function registerActiveGroup(g: ResponseTaskGroup): void {
  if (activeGroup && activeGroup.state !== 'done' && activeGroup.state !== 'cancelled') {
    activeGroup.cancel('superseded')
  }
  activeGroup = g
  notifyActiveGroup()
}

/**
 * Cancel the current active Group (if any) without immediately installing a
 * replacement. Used by callers that need to cancel the predecessor BEFORE
 * building the successor's children — otherwise the new playbackChild's
 * setCurrentToken preempts the old child's clearScope, leaving audioPlayback
 * stuck at paused=true after a voice-barge supersede. See
 * devdocs/voice-barge-structural-redesign.md §5 for the wider architecture.
 */
export function cancelCurrentActiveGroup(reason: CancelReason = 'superseded'): void {
  if (activeGroup && activeGroup.state !== 'done' && activeGroup.state !== 'cancelled') {
    activeGroup.cancel(reason)
  }
}

export function getActiveGroup(): ResponseTaskGroup | null {
  return activeGroup
}

export function clearActiveGroup(g: ResponseTaskGroup): void {
  if (activeGroup === g) {
    activeGroup = null
    notifyActiveGroup()
  }
}
