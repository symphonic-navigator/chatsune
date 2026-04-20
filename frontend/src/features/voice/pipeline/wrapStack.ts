import {
  WRAPPING_OPEN_PATTERN,
  WRAPPING_CLOSE_PATTERN,
} from '../expressionTags'

// Scan `text` and derive the resulting wrap stack, starting from
// `enteringStack`. Open markers of canonical wrapping tags push; matching
// close markers pop. Underflow pops and close markers whose name does not
// match the stack top are ignored — the LLM owns that mistake.
export function scanSegment(text: string, enteringStack: readonly string[]): string[] {
  const stack: string[] = [...enteringStack]
  const combined = new RegExp(
    `${WRAPPING_OPEN_PATTERN.source}|${WRAPPING_CLOSE_PATTERN.source}`,
    'g',
  )
  for (const match of text.matchAll(combined)) {
    const token = match[0]
    if (token.startsWith('</')) {
      const name = token.slice(2, -1)
      if (stack.length > 0 && stack[stack.length - 1] === name) {
        stack.pop()
      }
      // else: ignore (underflow or mismatch)
    } else {
      const name = token.slice(1, -1)
      stack.push(name)
    }
  }
  return stack
}

// Produce the re-wrapped segment for emission at a sentence (or sub-segment)
// boundary. Prepends opens from `enteringStack` in stack order, appends closes
// from `leavingStack` in reverse order. Interior tags inside `text` are
// preserved verbatim — the two stacks reconstruct scope at the ends only.
export function wrapSegmentWithActiveStack(
  text: string,
  enteringStack: readonly string[],
  leavingStack: readonly string[],
): string {
  const opens = enteringStack.map((tag) => `<${tag}>`).join('')
  const closes = [...leavingStack].reverse().map((tag) => `</${tag}>`).join('')
  return `${opens}${text}${closes}`
}
