import { getPlugin } from './registry'
import { useIntegrationsStore } from './store'
import type { TagExecutionResult } from './types'

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

/**
 * Streaming tag buffer. Accumulates characters when a potential integration
 * tag is being received, then either executes it or flushes as plain text.
 *
 * Tag format: <integration_id command arg1 arg2 ...>
 *
 * Usage: create one instance per streaming session (correlation).
 * Call process(delta) for each content delta. It returns the text that
 * should be appended to the visible content — tags are replaced with
 * their execution result.
 */
export class ResponseTagBuffer {
  private buffer = ''
  private insideTag = false
  private tagPrefixes: Set<string>
  private pendingExecutions: Promise<void>[] = []

  private onTagResolved: (placeholder: string, replacement: string) => void

  constructor(onTagResolved: (placeholder: string, replacement: string) => void) {
    this.tagPrefixes = getTagPrefixes()
    this.onTagResolved = onTagResolved
  }

  /**
   * Process an incoming content delta. Returns the text to append to
   * visible output. Tags in progress are buffered (returned as '').
   * Completed tags are replaced with a placeholder that gets swapped
   * asynchronously once the tag executes.
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
            const placeholder = `\u200B[${integrationId}:${command}]\u200B`
            output += placeholder

            const execution = this.executeTag(integrationId, command, args, placeholder)
            this.pendingExecutions.push(execution)
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
   * Flush any remaining buffer (called at end of stream).
   */
  flush(): string {
    const remainder = this.buffer
    this.buffer = ''
    this.insideTag = false
    return remainder
  }

  /** Wait for all pending tag executions to complete. */
  async awaitPending(): Promise<void> {
    await Promise.allSettled(this.pendingExecutions)
    this.pendingExecutions = []
  }

  private async executeTag(
    integrationId: string,
    command: string,
    args: string[],
    placeholder: string,
  ): Promise<void> {
    const plugin = getPlugin(integrationId)
    if (!plugin?.executeTag) {
      this.onTagResolved(placeholder, `_[${integrationId}: no tag handler]_`)
      return
    }

    const config = useIntegrationsStore.getState().getConfig(integrationId)
    const userConfig = config?.config ?? {}

    try {
      const result: TagExecutionResult = await plugin.executeTag(command, args, userConfig)
      this.onTagResolved(placeholder, result.displayText)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      this.onTagResolved(placeholder, `_[${integrationId} error: ${msg}]_`)
    }
  }
}
