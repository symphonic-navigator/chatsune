import { getPlugin } from './registry'
import { useIntegrationsStore } from './store'
import type { IntegrationInlineTrigger, TagExecutionResult } from './types'

/**
 * Stream source for tag emission. Mirrors the `source` field of
 * `IntegrationInlineTrigger` and decides — together with the plugin's
 * `syncWithTts` flag — whether the trigger fires immediately or is parked
 * in the pendingEffectsMap for the audio pipeline to claim.
 */
export type StreamSource = 'live_stream' | 'text_only' | 'read_aloud'

/**
 * One parked trigger waiting for a sentence boundary. The audio pipeline
 * consumes these by matching the placeholder embedded in the synth text
 * against `effectId` and producing an `IntegrationInlineTrigger` event.
 */
export interface PendingEffect {
  effectId: string
  integration_id: string
  command: string
  args: string[]
  pillContent: string
  effectPayload: unknown
}

/**
 * Collects known integration IDs that have response tag support.
 */
function getTagPrefixes(): Set<string> {
  const prefixes = new Set<string>()
  const defs = useIntegrationsStore.getState().definitions
  for (const d of defs) {
    if (d.has_response_tags) {
      prefixes.add(d.id)
    }
  }
  return prefixes
}

/** UUID with a Math.random fallback for older test environments. */
function newEffectId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto
  if (c?.randomUUID) {
    return c.randomUUID()
  }
  // RFC4122-ish fallback — collision-resistant enough for a short-lived
  // placeholder. Only used when crypto.randomUUID is unavailable.
  const hex = (n: number) => Math.floor(Math.random() * n).toString(16)
  return `${hex(0xffffffff)}-${hex(0xffff)}-4${hex(0xfff)}-${hex(0xfff)}-${hex(0xffffffffffff)}`
}

/**
 * Streaming tag buffer.
 *
 * Accumulates characters when a potential integration tag is being received,
 * then either executes it (synchronously) or flushes the buffered text as
 * plain output. Tag format: `<integration_id command arg1 arg2 ...>`.
 *
 * Each detected and known tag is replaced inline with a UUID placeholder of
 * the shape `​[effect:<uuid>]​` (zero-width-space wrapped). The plugin's
 * `executeTag` runs synchronously and returns metadata describing the pill
 * and the trigger event; an optional `sideEffect` thunk carries any async
 * work (hardware calls etc.) and is fired-and-forgotten.
 *
 * Emission policy:
 * - When `syncWithTts === false` OR the source is not `live_stream`/`read_aloud`,
 *   the trigger event fires immediately via `emitTrigger`.
 * - Otherwise the entry is parked in `pendingEffectsMap` and fired later by
 *   the audio pipeline at the corresponding sentence boundary.
 *
 * Use one instance per streaming session (correlation).
 */
export class ResponseTagBuffer {
  private buffer = ''
  private insideTag = false
  private tagPrefixes: Set<string>

  private onTagResolved: (placeholder: string, replacement: string) => void
  private streamSource: StreamSource
  private pending: Map<string, PendingEffect>
  private emitTrigger: (event: IntegrationInlineTrigger) => void

  /**
   * @param onTagResolved Called when a tag's pill content is decided. Carries
   *   the placeholder string and the replacement to swap into the visible
   *   stream. For successfully executed tags this is currently the same
   *   placeholder (rendering is handled elsewhere); for error pills the
   *   replacement is the human-readable error text.
   * @param streamSource Which kind of stream this buffer feeds. Defaults to
   *   `'live_stream'` so existing 1-arg callers continue to compile while
   *   Phase 5 wires up the real source.
   * @param pendingEffectsMap External map that holds parked triggers waiting
   *   for a sentence boundary. Defaults to a fresh local map; legacy callers
   *   that don't consume the map keep working unchanged.
   * @param emitTrigger Callback for immediate trigger emission. Defaults to
   *   a no-op — Phase 5 will pass an event-bus dispatcher.
   */
  constructor(
    onTagResolved: (placeholder: string, replacement: string) => void,
    streamSource: StreamSource = 'live_stream',
    pendingEffectsMap: Map<string, PendingEffect> = new Map(),
    emitTrigger: (event: IntegrationInlineTrigger) => void = () => undefined,
  ) {
    this.tagPrefixes = getTagPrefixes()
    this.onTagResolved = onTagResolved
    this.streamSource = streamSource
    this.pending = pendingEffectsMap
    this.emitTrigger = emitTrigger
  }

  /**
   * Process an incoming content delta. Returns the text to append to
   * visible output. Tags in progress are buffered (returned as ''),
   * completed known tags are replaced with a UUID placeholder.
   */
  process(delta: string): string {
    if (this.tagPrefixes.size === 0) return delta

    let output = ''

    for (const ch of delta) {
      if (this.insideTag) {
        this.buffer += ch
        if (ch === '>') {
          const tagContent = this.buffer.slice(1, -1).trim()
          const parts = tagContent.split(/\s+/)
          const integrationId = parts[0]

          if (this.tagPrefixes.has(integrationId)) {
            const command = parts[1] || ''
            const args = parts.slice(2)
            output += this.handleTag(integrationId, command, args)
          } else {
            output += this.buffer
          }

          this.buffer = ''
          this.insideTag = false
        }
      } else if (ch === '<') {
        this.insideTag = true
        this.buffer = '<'
      } else {
        output += ch
      }
    }

    return output
  }

  /**
   * Flush any remaining buffer (called at end of stream) and emit any
   * triggers still parked in the pending map. Returns the leftover
   * buffered text, or `''` if there was none.
   */
  flush(): string {
    const remainder = this.buffer
    this.buffer = ''
    this.insideTag = false

    for (const entry of this.pending.values()) {
      this.emitTrigger(this.toEvent(entry))
    }
    this.pending.clear()

    return remainder
  }

  private handleTag(integrationId: string, command: string, args: string[]): string {
    const effectId = newEffectId()
    const placeholder = `​[effect:${effectId}]​`

    const plugin = getPlugin(integrationId)
    if (!plugin?.executeTag) {
      this.onTagResolved(placeholder, `[error: no tag handler for ${integrationId}]`)
      return placeholder
    }

    const config = useIntegrationsStore.getState().getConfig(integrationId)
    const userConfig = config?.config ?? {}

    let result: TagExecutionResult
    try {
      result = plugin.executeTag(command, args, userConfig)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      this.onTagResolved(placeholder, `[error: ${integrationId}: ${msg}]`)
      return placeholder
    }

    if (result.sideEffect) {
      // Fire-and-forget: hardware calls etc. must not block the pill or the
      // trigger event. Any rejection is logged and ignored.
      void result.sideEffect().catch((err) => {
        console.error(`[integrations] sideEffect failed for ${integrationId}:`, err)
      })
    }

    const entry: PendingEffect = {
      effectId,
      integration_id: integrationId,
      command,
      args,
      pillContent: result.pillContent,
      effectPayload: result.effectPayload,
    }
    this.pending.set(effectId, entry)

    const ttsActive = this.streamSource === 'live_stream' || this.streamSource === 'read_aloud'
    if (!result.syncWithTts || !ttsActive) {
      this.emitTrigger(this.toEvent(entry))
      this.pending.delete(effectId)
    }

    return placeholder
  }

  private toEvent(entry: PendingEffect): IntegrationInlineTrigger {
    return {
      integration_id: entry.integration_id,
      command: entry.command,
      args: entry.args,
      payload: entry.effectPayload,
      source: this.streamSource,
      // The caller (event-bus dispatcher in Phase 5) is responsible for
      // populating this from the active streaming correlation id.
      correlation_id: '',
      timestamp: new Date().toISOString(),
    }
  }
}
