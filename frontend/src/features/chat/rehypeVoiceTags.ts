import type { Plugin } from 'unified'
import type { Root, Element, Text, RootContent, ElementContent } from 'hast'
import { visit } from 'unist-util-visit'

import { ANY_TAG_PATTERN } from '../voice/expressionTags'

// A `raw` hast node is emitted by remark-rehype when it encounters inline
// HTML in the markdown source (e.g. `<whisper>…</whisper>`). We need a
// local type because hast's TypeScript types do not export it.
interface RawNode {
  type: 'raw'
  value: string
}

type TextishNode = Text | RawNode

// Walk the HAST and split every text / raw node (outside <code>/<pre>) into
// a sequence of text/raw and <span class="voice-tag"> nodes, one span per
// canonical inline/wrapping tag occurrence.
//
// Non-match segments keep the same node type as the original (so raw HTML
// around the tag is preserved as-is). The pill's inner child is always a
// `text` node so angle brackets inside the tag name get HTML-escaped in the
// rendered output (the user sees `<whisper>` literally, not a broken element).
const rehypeVoiceTags: Plugin<[], Root> = () => (tree) => {
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

    const regex = new RegExp(ANY_TAG_PATTERN.source, 'g')
    const original = node.value
    if (!regex.test(original)) return
    regex.lastIndex = 0

    const nodeType = node.type // 'text' or 'raw'
    const replacements: Array<TextishNode | Element> = []
    let cursor = 0

    for (const match of original.matchAll(regex)) {
      const idx = match.index ?? 0
      if (idx > cursor) {
        // Preserve the surrounding content with the same node type so raw
        // HTML outside the tag is not re-escaped.
        replacements.push({ type: nodeType, value: original.slice(cursor, idx) } as TextishNode)
      }
      const pill: Element = {
        type: 'element',
        tagName: 'span',
        properties: { className: ['voice-tag'] },
        // Always a text child so angle brackets are escaped to entities inside the pill.
        children: [{ type: 'text', value: match[0] }],
      }
      replacements.push(pill)
      cursor = idx + match[0].length
    }
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

export default rehypeVoiceTags
