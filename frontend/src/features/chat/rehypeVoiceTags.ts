import type { Plugin } from 'unified'
import type { Root, Element, Text, RootContent, ElementContent } from 'hast'
import { visit, SKIP } from 'unist-util-visit'

import { ANY_TAG_PATTERN } from '../voice/expressionTags'

// Walk the HAST and split every text node (outside <code>/<pre>) into
// a sequence of text and <span class="voice-tag"> nodes, one span per
// canonical inline/wrapping tag occurrence.
const rehypeVoiceTags: Plugin<[], Root> = () => (tree) => {
  // First pass: mark code/pre subtrees as skipped.
  // We use visit's return value to short-circuit traversal into code blocks.
  visit(tree, 'element', (node: Element) => {
    if (node.tagName === 'code' || node.tagName === 'pre') {
      return SKIP
    }
    return undefined
  })

  // Second pass: split text nodes that contain canonical tag patterns.
  visit(tree, 'text', (node: Text, index, parent) => {
    if (!parent || index === undefined) return
    if ('tagName' in parent) {
      const tag = (parent as Element).tagName
      if (tag === 'code' || tag === 'pre') return
    }

    const regex = new RegExp(ANY_TAG_PATTERN.source, 'g')
    const original = node.value
    if (!regex.test(original)) return
    regex.lastIndex = 0

    const replacements: Array<Text | Element> = []
    let cursor = 0
    for (const match of original.matchAll(regex)) {
      const idx = match.index ?? 0
      if (idx > cursor) {
        replacements.push({ type: 'text', value: original.slice(cursor, idx) })
      }
      const pill: Element = {
        type: 'element',
        tagName: 'span',
        properties: { className: ['voice-tag'] },
        children: [{ type: 'text', value: match[0] }],
      }
      replacements.push(pill)
      cursor = idx + match[0].length
    }
    if (cursor < original.length) {
      replacements.push({ type: 'text', value: original.slice(cursor) })
    }

    const siblings = (parent as { children: (RootContent | ElementContent)[] }).children
    siblings.splice(index, 1, ...(replacements as (RootContent | ElementContent)[]))
    return index + replacements.length
  })
}

export default rehypeVoiceTags
