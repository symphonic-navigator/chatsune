const EMOJI_RE = /\p{Extended_Pictographic}/u

/** Insert an emoji at the textarea's caret with Chatsune's spacing rules:
 *  add a leading space iff the previous char is non-empty, non-whitespace,
 *  non-emoji; add a trailing space iff the next char is non-empty,
 *  non-whitespace, non-emoji. Returns the new value and the resulting
 *  caret position so the caller can re-apply selection after re-render. */
export function insertEmojiAtCursor(
  textarea: HTMLTextAreaElement,
  emoji: string,
): { value: string; cursor: number } {
  const { value, selectionStart, selectionEnd } = textarea
  const before = value.slice(0, selectionStart)
  const after = value.slice(selectionEnd)

  // Look at the previous/next *code point*, not the previous/next UTF-16
  // code unit. `slice(-1)` would split surrogate pairs in half and the
  // EMOJI_RE check would falsely return false for an actual emoji.
  const prevCodepoints = [...before]
  const nextCodepoints = [...after]
  const prevChar = prevCodepoints[prevCodepoints.length - 1] ?? ''
  const nextChar = nextCodepoints[0] ?? ''

  const needsLead =
    prevChar !== '' && !/\s/.test(prevChar) && !EMOJI_RE.test(prevChar)
  const needsTrail =
    nextChar !== '' && !/\s/.test(nextChar) && !EMOJI_RE.test(nextChar)

  const insertion = (needsLead ? ' ' : '') + emoji + (needsTrail ? ' ' : '')
  const newValue = before + insertion + after
  const newCursor = before.length + insertion.length
  return { value: newValue, cursor: newCursor }
}
