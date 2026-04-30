import { useEffect } from 'react'
import { eventBus } from '../../core/websocket/eventBus'
import { useChatStore } from '../../core/store/chatStore'
import { useNotificationStore } from '../../core/store/notificationStore'
import { Topics } from '../../core/types/events'
import type { BaseEvent } from '../../core/types/events'
import { sendMessage } from '../../core/websocket/connection'
import type { ArtefactRef, KnowledgeContextItem, PtiOverflow } from '../../core/api/chat'
import type { ImageRefDto } from '../../core/api/images'
import type { TimelineEntry } from '../../core/api/chat'
import { ResponseTagBuffer, type PendingEffect } from '../integrations/responseTagProcessor'
import { emitInlineTrigger } from '../integrations/inlineTriggerBus'
import { useIntegrationsStore } from '../integrations/store'
import { getActiveGroup, subscribeActiveGroup } from './responseTaskGroup'
import { useCockpitStore } from './cockpit/cockpitStore'

let activeTagBuffer: ResponseTagBuffer | null = null

/**
 * Flush the module-level active tag buffer if one exists, then null it out.
 * Exported so cancellation paths (Group cancellation via barge / supersede /
 * teardown / user-stop) can drain parked inline-trigger entries before the
 * buffer reference is replaced. Without this, a stream cancelled before
 * CHAT_STREAM_ENDED / CHAT_STREAM_ERROR would leak its parked entries when
 * the next CHAT_STREAM_STARTED installs a fresh buffer.
 */
export function flushActiveTagBufferOnCancel(): void {
  if (activeTagBuffer) {
    activeTagBuffer.flush()
    activeTagBuffer = null
  }
}

// Module-level handler exported for unit testing. The hook wires this into
// the event bus; tests call it directly without mounting a component.
export function handleChatEvent(
  event: BaseEvent,
  sendMessageFn: typeof sendMessage,
  sessionId: string | null,
): void {
  const getStore = useChatStore.getState
  const p = event.payload as Record<string, unknown>

  switch (event.type) {
    case Topics.CHAT_STREAM_STARTED: {
      if (p.session_id !== sessionId) return
      getStore().startStreaming(event.correlation_id)
      // Create tag buffer for this streaming session.
      const enabledIds = useIntegrationsStore.getState().getEnabledIds()
      if (enabledIds.length > 0) {
        // The active Group (created by ChatView before the WS send) carries
        // the per-stream pendingEffectsMap and streamSource. The buffer must
        // share both with the audio pipeline's parser so sentence-synced
        // tags are claimed by the matching SpeechSegment instead of firing
        // immediately. When no Group is active (e.g. server-initiated
        // assistant turn before our send path runs), fall back to a fresh
        // local map and `'text_only'` so the buffer still works in
        // immediate-emit mode.
        const activeGroup = getActiveGroup()
        const fallbackMap = new Map<string, PendingEffect>()
        const fallbackPillMap = new Map<string, string>()
        const sharedMap =
          activeGroup && activeGroup.id === event.correlation_id
            ? (activeGroup.pendingEffectsMap ?? fallbackMap)
            : fallbackMap
        const sharedPillMap =
          activeGroup && activeGroup.id === event.correlation_id
            ? (activeGroup.renderedPillsMap ?? fallbackPillMap)
            : fallbackPillMap
        const streamSource: 'live_stream' | 'text_only' =
          activeGroup && activeGroup.id === event.correlation_id
            ? activeGroup.streamSource
            : 'text_only'
        const correlationId = event.correlation_id
        activeTagBuffer = new ResponseTagBuffer(
          (placeholder, replacement) => {
            getStore().replaceInStreamingContent(placeholder, replacement)
          },
          streamSource,
          sharedMap,
          (trigger) => emitInlineTrigger(trigger, correlationId),
          sharedPillMap,
        )
      } else {
        activeTagBuffer = null
      }
      break
    }
    case Topics.CHAT_CONTENT_DELTA: {
      const g = getActiveGroup()
      if (!g || g.id !== event.correlation_id) {
        console.debug(`[useChatStream] drop CHAT_CONTENT_DELTA (no matching group, id=${event.correlation_id})`)
        return
      }
      const rawDelta = p.delta as string
      // Tag buffer still lives here — it transforms deltas before storage.
      const visibleDelta = activeTagBuffer ? activeTagBuffer.process(rawDelta) : rawDelta
      g.onDelta(visibleDelta)
      break
    }
    case Topics.CHAT_THINKING_DELTA: {
      if (event.correlation_id !== getStore().correlationId) return
      getStore().appendStreamingThinking(p.delta as string)
      break
    }
    case Topics.CHAT_STREAM_SLOW: {
      if (event.correlation_id !== getStore().correlationId) return
      getStore().setStreamingSlow(true)
      break
    }
    case Topics.CHAT_VISION_DESCRIPTION: {
      getStore().upsertVisionDescription(event.correlation_id, {
        file_id: p.file_id as string,
        display_name: p.display_name as string,
        model_id: p.model_id as string,
        status: p.status as 'pending' | 'success' | 'error',
        text: (p.text as string | null) ?? null,
        error: (p.error as string | null) ?? null,
      })
      break
    }
    case Topics.CHAT_TOOL_CALL_STARTED: {
      if (event.correlation_id !== getStore().correlationId) return
      getStore().addToolCall({
        id: p.tool_call_id as string,
        toolName: p.tool_name as string,
        arguments: p.arguments as Record<string, unknown>,
        status: 'running',
      })
      break
    }
    case Topics.CHAT_TOOL_CALL_COMPLETED: {
      if (event.correlation_id !== getStore().correlationId) return
      getStore().completeToolCall(p.tool_call_id as string)
      const artefactRef = p.artefact_ref as ArtefactRef | null | undefined
      const imageRefsRaw = p.image_refs as unknown
      const moderatedCount = (p.moderated_count as number | undefined) ?? 0
      const toolName = p.tool_name as string | undefined
      const success = (p.success as boolean | undefined) ?? true
      const toolCallId = p.tool_call_id as string
      const args = (p.arguments as Record<string, unknown> | undefined) ?? {}

      // Failed tool call — always becomes a generic pill regardless of
      // tool name (a failed knowledge_search must NOT render as an empty
      // KnowledgePills). This branch is hoisted above the tool-name
      // dispatch so failures of knowledge_search, web_search, and
      // web_fetch are not silently swallowed.
      if (toolName && !success) {
        const entry: TimelineEntry = {
          kind: 'tool_call',
          seq: 0,
          tool_call_id: toolCallId,
          tool_name: toolName,
          arguments: args,
          success: false,
          moderated_count: moderatedCount,
        }
        getStore().appendStreamingEvent(entry)
      } else if (artefactRef) {
        const entry: TimelineEntry = {
          kind: 'artefact',
          seq: 0,
          ref: artefactRef,
        }
        getStore().appendStreamingEvent(entry)
      } else if (toolName === 'generate_image') {
        // Mirrors the artefact_ref pattern: the inference loop attaches
        // image_refs to the tool_call.completed event for generate_image so
        // the frontend can render the inline images live without waiting
        // for a session reload.
        const refs: ImageRefDto[] = Array.isArray(imageRefsRaw) ? (imageRefsRaw as ImageRefDto[]) : []
        if (refs.length > 0 || moderatedCount > 0) {
          const entry: TimelineEntry = {
            kind: 'image',
            seq: 0,
            refs,
            moderated_count: moderatedCount,
          }
          getStore().appendStreamingEvent(entry)
        }
      } else if (
        toolName
        && toolName !== 'knowledge_search'
        && toolName !== 'web_search'
        && toolName !== 'web_fetch'
      ) {
        // Successful generic tool — gets a `tool_call` entry. The three
        // search/fetch tools are intentionally excluded on success
        // because their dedicated events (KNOWLEDGE_SEARCH_COMPLETED /
        // CHAT_WEB_SEARCH_CONTEXT) carry the result data needed for
        // their typed entries.
        const entry: TimelineEntry = {
          kind: 'tool_call',
          seq: 0,
          tool_call_id: toolCallId,
          tool_name: toolName,
          arguments: args,
          success,
          moderated_count: moderatedCount,
        }
        getStore().appendStreamingEvent(entry)
      }
      break
    }
    case Topics.CHAT_WEB_SEARCH_CONTEXT: {
      if (event.correlation_id !== getStore().correlationId) return
      const items = p.items as Array<{ title: string; url: string; snippet: string; source_type?: 'search' | 'fetch' }>
      const entry: TimelineEntry = {
        kind: 'web_search',
        seq: 0,
        items,
      }
      getStore().appendStreamingEvent(entry)
      break
    }
    case Topics.CHAT_STREAM_ENDED: {
      if (p.session_id !== sessionId) return
      const g = getActiveGroup()
      if (g && g.id === event.correlation_id) g.onStreamEnd()
      // Snapshot the live pill map. The Map reference is shared with the
      // active Group; we hand an independent shallow copy to the chat store
      // so the post-stream Message renders pills correctly even though
      // `content` now carries placeholders instead of raw tags. flush()
      // never writes to renderedPillsMap (only handleTag() during process()
      // does) so the snapshot timing relative to flush() is irrelevant —
      // we take it here for clarity, before the local buffer reference is
      // nulled out below.
      const livePillContents: Map<string, string> | undefined =
        g && g.id === event.correlation_id && g.renderedPillsMap
          ? new Map(g.renderedPillsMap)
          : undefined
      // Flush incomplete tag buffer
      if (activeTagBuffer) {
        const remainder = activeTagBuffer.flush()
        if (remainder) getStore().appendStreamingContent(remainder)
        activeTagBuffer = null
      }
      const contextStatus = (p.context_status as 'green' | 'yellow' | 'orange' | 'red') ?? 'green'
      const fillPercentage = (p.context_fill_percentage as number) ?? 0
      const usedTokens = (p.context_used_tokens as number | undefined) ?? 0
      const maxTokens = (p.context_max_tokens as number | undefined) ?? 0
      const rawStatus = (p.status as string | undefined) ?? 'completed'
      const messageStatus: 'completed' | 'aborted' | 'refused' =
        rawStatus === 'refused'
          ? 'refused'
          : rawStatus === 'aborted'
            ? 'aborted'
            : 'completed'
      const ttft = (p.time_to_first_token_ms as number | undefined) ?? null
      const tps = (p.tokens_per_second as number | undefined) ?? null
      const genDuration = (p.generation_duration_ms as number | undefined) ?? null
      const providerName = (p.provider_name as string | undefined) ?? null
      const modelName = (p.model_name as string | undefined) ?? null

      // Finalise the streamed message whenever the backend persisted
      // it — even on cancelled/error runs, the backend now saves the
      // partial content so we do not throw away tokens the user has
      // already seen. The ``status`` is still surfaced so the bubble
      // can be badged as interrupted if we want to.
      // Refused messages may have no content — still persist them so
      // the refusal band shows immediately without a page refresh.
      const backendMessageId = p.message_id as string | undefined
      const content = getStore().streamingContent
      const thinking = getStore().streamingThinking
      const refusalText = getStore().streamingRefusalText
      // The persisted timeline arrives on the stream-ended payload as
      // `events`. We adopt it verbatim — anything we accumulated client-side
      // during the stream is discarded by `finishStreaming`. While the
      // backend is in transition (BE rollout lags FE), fall back to the
      // client-built list so live runs still show pills.
      const persistedEvents = p.events as TimelineEntry[] | null | undefined
      const events: TimelineEntry[] = Array.isArray(persistedEvents)
        ? persistedEvents
        : getStore().streamingEvents
      // Auto-read trigger: if the session has auto-read on and the message
      // completed normally with content, signal the ReadAloudButton for this
      // messageId to start playback. Lives here (not in AssistantMessage)
      // because the messageId changes from optimistic to backend at commit
      // time, which remounts the component and loses any local transition.
      if (
        backendMessageId
        && content
        && messageStatus === 'completed'
        && getStore().autoRead
      ) {
        useCockpitStore.getState().requestAutoRead(backendMessageId)
      }

      // Trust ``backendMessageId`` whenever the backend sent one: the
      // backend has the authoritative view of what was persisted, and any
      // streamed content (or thinking, or refusal) has already been folded
      // into the persisted document. Falling back to local content/thinking
      // checks risked dropping a fully-streamed assistant turn whenever a
      // non-fatal error (e.g. unknown tool) reset the per-iteration
      // accumulators on the server before the persistence point.
      if (backendMessageId) {
        getStore().finishStreaming(
          {
            id: backendMessageId,
            session_id: sessionId ?? '',
            role: 'assistant',
            content,
            thinking: thinking || null,
            token_count: 0,
            attachments: null,
            web_search_context: null,
            knowledge_context: null,
            events: events.length > 0 ? events : null,
            refusal_text: refusalText || null,
            created_at: new Date().toISOString(),
            status: messageStatus,
            time_to_first_token_ms: ttft,
            tokens_per_second: tps,
            generation_duration_ms: genDuration,
            provider_name: providerName,
            model_name: modelName,
          },
          contextStatus,
          fillPercentage,
          usedTokens,
          maxTokens,
          livePillContents,
        )
      } else {
        // No persisted message — discard the optimistic streaming state.
        // After the backend's matching guard fix this branch should only
        // fire on genuine internal errors that produced zero content AND
        // zero thinking. If it ever fires with non-empty streamed content,
        // investigate: it indicates a backend persistence regression.
        getStore().cancelStreaming()
      }
      getStore().setContextStatus(contextStatus)
      getStore().setContextFillPercentage(fillPercentage)
      getStore().setContextTokens(usedTokens, maxTokens)
      break
    }
    case Topics.CHAT_STREAM_ERROR: {
      const errorCode = p.error_code as string
      // Session-level errors arrive outside a streaming context —
      // they carry their own correlation id that the frontend never
      // saw, so we let them through unconditionally. This includes
      // rejections from handle_chat_edit that fire before any stream
      // has started (invalid_edit, session_busy, edit_target_missing,
      // edit_failed).
      const sessionLevelCodes = new Set([
        'session_expired',
        'invalid_edit',
        'edit_target_missing',
        'edit_failed',
      ])
      const isSessionError = sessionLevelCodes.has(errorCode)
      if (!isSessionError && event.correlation_id !== getStore().correlationId) return

      const recoverable = p.recoverable as boolean
      const userMessage = p.user_message as string
      getStore().setError({
        errorCode,
        recoverable,
        userMessage,
      })
      getStore().setWaitingForResponse(false)

      // Flush the tag buffer here too: a stream that errors before its
      // CHAT_STREAM_ENDED counterpart still has parked effects in the
      // pending map, and dropping the buffer without flush() would lose
      // those triggers entirely.
      if (activeTagBuffer) {
        const remainder = activeTagBuffer.flush()
        if (remainder) getStore().appendStreamingContent(remainder)
        activeTagBuffer = null
      }

      if (errorCode === 'refusal') {
        getStore().setStreamingRefusalText(userMessage)
      }

      // Session-level errors have their own banner path (ChatView
      // renders them inline above the composer); everything else
      // surfaces through the toast system so the user is not left
      // staring at a silently broken reply. Recoverable errors get
      // an inline Regenerate action bound to the session that was
      // current when the error arrived.
      if (!isSessionError) {
        const sessionIdAtError = sessionId
        const title = (() => {
          if (errorCode === 'refusal') return 'Request declined'
          if (recoverable) return 'Response interrupted'
          return 'Error'
        })()
        const action = recoverable && sessionIdAtError
          ? {
              label: 'Regenerate',
              onClick: () => {
                sendMessageFn({
                  type: 'chat.regenerate',
                  session_id: sessionIdAtError,
                })
              },
            }
          : undefined
        useNotificationStore.getState().addNotification({
          level: 'error',
          title,
          message: userMessage,
          action,
        })
      }
      break
    }
    case Topics.CHAT_MESSAGE_CREATED: {
      if (p.session_id !== sessionId) return
      const knowledgeContext =
        (p.knowledge_context as KnowledgeContextItem[] | null | undefined) ?? null
      const ptiOverflow = (p.pti_overflow as PtiOverflow | null | undefined) ?? null
      const clientId = p.client_message_id as string | undefined
      if (clientId) {
        const idx = getStore().messages.findIndex((m) => m.id === clientId)
        if (idx !== -1) {
          getStore().swapMessageId(clientId, p.message_id as string, {
            knowledge_context: knowledgeContext,
            pti_overflow: ptiOverflow,
          })
          break
        }
      }
      // Fallback: append if we have no matching optimistic entry
      // (e.g. another tab, or a server-initiated user message).
      getStore().appendMessage({
        id: p.message_id as string,
        session_id: sessionId ?? '',
        role: p.role as 'user' | 'assistant',
        content: p.content as string,
        thinking: null,
        token_count: (p.token_count as number) ?? 0,
        attachments: null,
        web_search_context: null,
        knowledge_context: knowledgeContext,
        pti_overflow: ptiOverflow,
        created_at: new Date().toISOString(),
      })
      break
    }
    case Topics.CHAT_MESSAGES_TRUNCATED: {
      if (p.session_id !== sessionId) return
      getStore().truncateAfter(p.after_message_id as string)
      break
    }
    case Topics.CHAT_MESSAGE_UPDATED: {
      if (p.session_id !== sessionId) return
      getStore().updateMessage(p.message_id as string, p.content as string, p.token_count as number)
      break
    }
    case Topics.CHAT_MESSAGE_DELETED: {
      if (p.session_id !== sessionId) return
      getStore().deleteMessage(p.message_id as string)
      break
    }
    case Topics.CHAT_SESSION_TITLE_UPDATED: {
      if (p.session_id !== sessionId) return
      getStore().setSessionTitle(p.title as string)
      break
    }
    case Topics.CHAT_SESSION_TOOLS_UPDATED: {
      // Legacy event — no-op, superseded by CHAT_SESSION_TOGGLES_UPDATED
      break
    }
    case Topics.CHAT_SESSION_TOGGLES_UPDATED: {
      if (p.session_id !== sessionId) return
      if (typeof p.tools_enabled === 'boolean') getStore().setToolsEnabled(p.tools_enabled)
      if (typeof p.auto_read === 'boolean') getStore().setAutoRead(p.auto_read)
      if ('reasoning_override' in p) {
        const ro = p.reasoning_override
        getStore().setReasoningOverride(typeof ro === 'boolean' ? ro : null)
      }
      break
    }
  }
}

export function useChatStream(sessionId: string | null) {
  useEffect(() => {
    if (!sessionId) return

    // TODO Phase 8: the old inference.lock.* events have been removed.
    // Re-add an equivalent hook once the new event shape (tied to a
    // connection_id) lands.
    const handleEvent = (event: BaseEvent) => handleChatEvent(event, sendMessage, sessionId)

    const unsub = eventBus.on('chat.*', handleEvent)
    // A stream that gets cancelled (barge, supersede, user-stop, teardown)
    // never reaches CHAT_STREAM_ENDED or CHAT_STREAM_ERROR, so the buffer
    // flush in those handlers does not run. Subscribe to the active-group
    // registry and flush whenever a Group transitions to `cancelled` so
    // parked entries do not leak into the next stream's buffer.
    const unsubGroup = subscribeActiveGroup((group) => {
      if (group && group.state === 'cancelled') {
        flushActiveTagBufferOnCancel()
      }
    })
    return () => {
      unsub()
      unsubGroup()
    }
  }, [sessionId])
}
