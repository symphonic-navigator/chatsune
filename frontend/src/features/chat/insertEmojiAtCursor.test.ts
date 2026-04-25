import { describe, expect, it } from 'vitest'
import { insertEmojiAtCursor } from './insertEmojiAtCursor'

function makeTextarea(value: string, selectionStart: number, selectionEnd = selectionStart) {
  const ta = document.createElement('textarea')
  ta.value = value
  ta.selectionStart = selectionStart
  ta.selectionEnd = selectionEnd
  return ta
}

describe('insertEmojiAtCursor', () => {
  it('inserts at empty input with no surrounding spaces', () => {
    const ta = makeTextarea('', 0)
    expect(insertEmojiAtCursor(ta, '😊')).toEqual({ value: '😊', cursor: 2 })
  })

  it('inserts at end of text-only input — leading space, no trailing', () => {
    const ta = makeTextarea('hello', 5)
    expect(insertEmojiAtCursor(ta, '😊')).toEqual({ value: 'hello 😊', cursor: 8 })
  })

  it('inserts at start of text-only input — no leading, trailing space', () => {
    const ta = makeTextarea('hello', 0)
    expect(insertEmojiAtCursor(ta, '😊')).toEqual({ value: '😊 hello', cursor: 3 })
  })

  it('inserts in the middle of text — both spaces', () => {
    const ta = makeTextarea('helloworld', 5)
    expect(insertEmojiAtCursor(ta, '😊')).toEqual({ value: 'hello 😊 world', cursor: 9 })
  })

  it('does not double-space after existing trailing space', () => {
    const ta = makeTextarea('hello ', 6)
    expect(insertEmojiAtCursor(ta, '😊')).toEqual({ value: 'hello 😊', cursor: 8 })
  })

  it('does not space between two emojis', () => {
    const ta = makeTextarea('😊', 2)
    expect(insertEmojiAtCursor(ta, '🔥')).toEqual({ value: '😊🔥', cursor: 4 })
  })

  it('does not space when previous char is whitespace', () => {
    const ta = makeTextarea('a\n', 2)
    expect(insertEmojiAtCursor(ta, '😊')).toEqual({ value: 'a\n😊', cursor: 4 })
  })

  it('replaces selected range', () => {
    const ta = makeTextarea('helloXXworld', 5, 7)
    expect(insertEmojiAtCursor(ta, '😊')).toEqual({ value: 'hello 😊 world', cursor: 9 })
  })
})
