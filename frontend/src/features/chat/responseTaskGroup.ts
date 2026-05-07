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
  /** Per-stream parking lot for inline-trigger effects awaiting a sentence
   *  boundary. Owned by the Group's caller (ChatView), shared with the
   *  ResponseTagBuffer constructed in `useChatStream` and with the
   *  audioParser invoked inside the sentencer child. Optional so non-voice
   *  text-only streams and tests can omit it. */
  pendingEffectsMap?: Map<string, import('../integrations/responseTagProcessor').PendingEffect>
  /** Per-stream durable mirror of every rendered pill, keyed by effectId.
   *  Owned by ChatView, shared with the ResponseTagBuffer in `useChatStream`
   *  and with the rehype plugin that resolves placeholders at render time.
   *  Distinct from `pendingEffectsMap` because the buffer never drains it —
   *  entries live for the streaming bubble's render lifetime. Optional so
   *  legacy tests can omit it. */
  renderedPillsMap?: Map<string, string>
  /** Origin of this Group's stream. Stamped onto every inline-trigger
   *  event emitted from this Group's pipeline. `'live_stream'` for active
   *  voice-mode replies, `'text_only'` for text-only chat streams. */
  streamSource?: 'live_stream' | 'text_only'
}

export interface ResponseTaskGroup {
  readonly id: string
  readonly sessionId: string
  readonly state: GroupState
  /** See `ResponseTaskGroupDeps.pendingEffectsMap`. Exposed so siblings
   *  outside the children chain (e.g. the chat-stream event handler) can
   *  share the same map with the audio pipeline. */
  readonly pendingEffectsMap: Map<string, import('../integrations/responseTagProcessor').PendingEffect> | null
  /** See `ResponseTaskGroupDeps.renderedPillsMap`. Exposed so consumers
   *  outside the children chain (e.g. the live-stream renderer) can read
   *  the same map the buffer is mirroring into. */
  readonly renderedPillsMap: Map<string, string> | null
  /** See `ResponseTaskGroupDeps.streamSource`. */
  readonly streamSource: 'live_stream' | 'text_only'
  onDelta(delta: string): void
  onStreamEnd(): void
  pause(): void
  resume(): void
  cancel(reason: CancelReason): void
}

function hash8(id: string): string {
  return id.slice(0, 8)
}

/**
 * Determine which (if any) WS frame to send when a Group is cancelled.
 *
 * Semantics by reason:
 * - `barge-retract`: the user barged in *before* any output had been
 *   rendered, so the original user message should be retracted from the
 *   transcript. We only send `chat.retract` when we're still in
 *   `before-first-delta` — once a delta has arrived, the assistant has
 *   already produced visible output, so we fall back to `chat.cancel`
 *   (server stops generation, transcript stays intact).
 * - `teardown`: the React tree is being unmounted (navigation away,
 *   voice toggle, mic press handing off control, etc.). The backend
 *   inference must continue and persist its result, so the user can
 *   come back to a full assistant reply on remount. Sending neither
 *   `chat.cancel` nor `chat.retract` is intentional.
 * - `barge-cancel` / `user-stop` / `superseded`: stop the in-flight
 *   stream but leave whatever has already been persisted alone — that
 *   is exactly `chat.cancel`.
 */
function wsFrameForCancel(
  reason: CancelReason,
  wasBeforeDelta: boolean,
  correlationId: string,
  sessionId: string,
): WsOutbound | null {
  switch (reason) {
    case 'teardown':
      return null
    case 'barge-retract':
      if (wasBeforeDelta) {
        return { type: 'chat.retract', correlation_id: correlationId, session_id: sessionId }
      }
      return { type: 'chat.cancel', correlation_id: correlationId }
    case 'barge-cancel':
    case 'user-stop':
    case 'superseded':
      return { type: 'chat.cancel', correlation_id: correlationId }
  }
}

export function createResponseTaskGroup(deps: ResponseTaskGroupDeps): ResponseTaskGroup {
  const { correlationId, sessionId, children, sendWsMessage, logger } = deps
  const pendingEffectsMap = deps.pendingEffectsMap ?? null
  const renderedPillsMap = deps.renderedPillsMap ?? null
  const streamSource = deps.streamSource ?? 'text_only'
  const prefix = `[group ${hash8(correlationId)}]`
  let state: GroupState = 'before-first-delta'

  logger.info(
    `${prefix} created (session=${sessionId}, children=${children.map((c) => c.name).join(',')})`,
  )

  function transition(next: GroupState, reason?: CancelReason): void {
    const reasonSuffix = reason ? ` (reason=${reason})` : ''
    logger.info(`${prefix} ${state} → ${next}${reasonSuffix}`)
    state = next
    notifyAll(sessionId, group, logger)
    if (state === 'done' || state === 'cancelled') {
      // Skip the clear + null-notify when the state change is a supersede;
      // registerActiveGroup is about to install the new group and notify
      // with it. Otherwise listeners would see a spurious null pulse
      // between the cancelled snapshot and the new-group snapshot, which
      // synchronous useSyncExternalStore subscribers (usePhase) read as
      // 'no active group' and briefly flip the voice phase to idle.
      if (reason !== 'superseded') {
        clearGroupForSession(sessionId)
      }
    }
  }

  function isState(expected: GroupState): boolean {
    return state === expected
  }

  const group: ResponseTaskGroup = {
    get id() { return correlationId },
    get sessionId() { return sessionId },
    get state() { return state },
    get pendingEffectsMap() { return pendingEffectsMap },
    get renderedPillsMap() { return renderedPillsMap },
    get streamSource() { return streamSource },

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
      void (async () => {
        for (const child of children) {
          if (!isState('tailing')) return
          try { await Promise.resolve(child.onStreamEnd(correlationId)) }
          catch (err) { logger.error(`${prefix} child ${child.name} onStreamEnd threw`, err) }
        }
        if (!isState('tailing')) return
        transition('done')
      })()
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
      const frame = wsFrameForCancel(reason, wasBeforeDelta, correlationId, sessionId)
      if (frame) sendWsMessage(frame)
      void Promise.allSettled(children.map(async (c) => {
        try { await c.teardown() }
        catch (err) { logger.error(`${prefix} child ${c.name} teardown threw`, err) }
      }))
    },
  }

  return group
}

// --- Registry --------------------------------------------------------------
//
// Background-completions: multiple inferences may stream concurrently for
// different sessions (e.g. user switches persona while a long answer is in
// flight). The registry therefore keys Groups by `sessionId`, not by a
// single global slot. Per-session supersede semantics still apply: a second
// register for the same session cancels the first.

const groupsBySession = new Map<string, ResponseTaskGroup>()

export type GroupListener = (
  sessionId: string,
  group: ResponseTaskGroup | null,
) => void

const listeners = new Set<GroupListener>()

export function subscribeGroups(fn: GroupListener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}

// Snapshot the set before iterating so a listener that synchronously
// unsubscribes itself (or another listener) during the callback does not
// break the loop. Listener errors are isolated to keep one faulty consumer
// from silencing the others.
function notifyAll(
  sessionId: string,
  group: ResponseTaskGroup | null,
  logger?: GroupLogger,
): void {
  const snapshot = Array.from(listeners)
  for (const fn of snapshot) {
    try {
      fn(sessionId, group)
    }
    catch (err) {
      if (logger) logger.error('[group registry] listener threw', err)
      else console.error('[group registry] listener threw', err)
    }
  }
}

export function registerActiveGroup(g: ResponseTaskGroup): void {
  const existing = groupsBySession.get(g.sessionId)
  if (
    existing
    && existing.state !== 'done'
    && existing.state !== 'cancelled'
    && existing !== g
  ) {
    existing.cancel('superseded')
  }
  groupsBySession.set(g.sessionId, g)
  notifyAll(g.sessionId, g)
}

/**
 * Cancel the active Group for the given session (if any) without immediately
 * installing a replacement. Used by callers that need to cancel the predecessor
 * BEFORE building the successor's children — otherwise the new playbackChild's
 * setCurrentToken preempts the old child's clearScope, leaving audioPlayback
 * stuck at paused=true after a voice-barge supersede. See
 * devdocs/voice-barge-structural-redesign.md §5 for the wider architecture.
 *
 * Replaces the old `cancelCurrentActiveGroup` from the single-slot registry.
 */
export function cancelGroupForSession(
  sessionId: string,
  reason: CancelReason = 'superseded',
): void {
  const g = groupsBySession.get(sessionId)
  if (g && g.state !== 'done' && g.state !== 'cancelled') {
    g.cancel(reason)
  }
}

export function getActiveGroupForSession(
  sessionId: string,
): ResponseTaskGroup | null {
  return groupsBySession.get(sessionId) ?? null
}

/** Iterate over every currently-active group across all sessions. */
export function forEachActiveGroup(fn: (g: ResponseTaskGroup) => void): void {
  for (const g of groupsBySession.values()) fn(g)
}

export function clearGroupForSession(sessionId: string): void {
  const g = groupsBySession.get(sessionId)
  if (g) {
    groupsBySession.delete(sessionId)
    notifyAll(sessionId, null)
  }
}
