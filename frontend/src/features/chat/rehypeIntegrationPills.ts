import type { Plugin } from 'unified'
import type { Root, Element, Text, RootContent, ElementContent } from 'hast'
import { visit } from 'unist-util-visit'

// A `raw` hast node is emitted by remark-rehype when it encounters inline
// HTML in the markdown source. We need a local type because hast's
// TypeScript types do not export it.
interface RawNode {
  type: 'raw'
  value: string
}

type TextishNode = Text | RawNode

/**
 * Match the streaming-buffer placeholder shape:
 *   <ZWSP>[effect:<uuid>]<ZWSP>
 * where <ZWSP> is U+200B. The UUID body is captured but kept permissive —
 * `crypto.randomUUID` produces RFC 4122 v4 ids, but the buffer falls back to
 * a Math.random hex shape on older test environments, so we accept any
 * `[0-9a-fA-F-]+` body.
 */
const PLACEHOLDER_RE = /​\[effect:([0-9a-fA-F-]+)\]​/g

export interface RehypeIntegrationPillsOptions {
  /** Map of effectId → pill content. Populated by the ResponseTagBuffer's
   *  durable pill mirror. Missing entries are treated as orphans (the
   *  placeholder is stripped from the rendered output, mirroring how voice
   *  tags are silently dropped if their content is unrecognised). */
  pillContents: Map<string, string>
}

/**
 * Walk the HAST and split every text / raw node (outside `<code>`/`<pre>`)
 * into a sequence of text/raw and `<span class="integration-pill">` nodes,
 * one span per integration-pill placeholder occurrence.
 *
 * The placeholder format is the one written by ResponseTagBuffer.handleTag:
 * `​[effect:<uuid>]​`. Each placeholder is resolved against the
 * provided `pillContents` map; resolved content is wrapped in a span; orphan
 * placeholders (no matching key) are stripped so a stale stream never leaks
 * raw markup into the rendered chat history.
 *
 * Mirrors the structure of `rehypeVoiceTags` so behaviour around code blocks
 * and raw HTML stays consistent between the two pill aesthetics.
 */
const rehypeIntegrationPills: Plugin<[RehypeIntegrationPillsOptions], Root> = (options) => {
  const pillContents = options?.pillContents ?? new Map<string, string>()

  return (tree) => {
    function processTextishNode(
      node: TextishNode,
      index: number | undefined,
      parent: { children: (RootContent | ElementContent)[] } | undefined,
    ): number | void {
      if (!parent || index === undefined) return
      if ('tagName' in parent) {
        const tag = (parent as Element).tagName
        if (tag === 'code' || tag === 'pre') return
      }

      const original = node.value
      // Cheap rejection for the common case (most text nodes contain no
      // placeholders at all).
      if (original.indexOf('​[effect:') === -1) return

      const regex = new RegExp(PLACEHOLDER_RE.source, 'g')
      const nodeType = node.type // 'text' or 'raw'
      const replacements: Array<TextishNode | Element> = []
      let cursor = 0
      let matched = false

      for (const match of original.matchAll(regex)) {
        matched = true
        const idx = match.index ?? 0
        const effectId = match[1]
        if (idx > cursor) {
          replacements.push({ type: nodeType, value: original.slice(cursor, idx) } as TextishNode)
        }
        const pillContent = pillContents.get(effectId)
        if (pillContent !== undefined) {
          const pill: Element = {
            type: 'element',
            tagName: 'span',
            properties: { className: ['integration-pill'] },
            children: [{ type: 'text', value: pillContent }],
          }
          replacements.push(pill)
        }
        // Orphan placeholder: drop it. A stale or expired live-stream id
        // should never appear as raw `[effect:...]` text in the message.
        cursor = idx + match[0].length
      }

      if (!matched) return
      if (cursor < original.length) {
        replacements.push({ type: nodeType, value: original.slice(cursor) } as TextishNode)
      }

      parent.children.splice(index, 1, ...(replacements as (RootContent | ElementContent)[]))
      return index + replacements.length
    }

    visit(tree, 'text', (node: Text, index, parent) => {
      return processTextishNode(node, index, parent as { children: (RootContent | ElementContent)[] } | undefined)
    })

    visit(tree, 'raw', (node: RawNode, index, parent) => {
      return processTextishNode(node, index, parent as { children: (RootContent | ElementContent)[] } | undefined)
    })
  }
}

export default rehypeIntegrationPills
