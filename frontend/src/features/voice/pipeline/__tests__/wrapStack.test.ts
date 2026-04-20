import { describe, it, expect } from 'vitest'
import { scanSegment, wrapSegmentWithActiveStack } from '../wrapStack'

describe('scanSegment', () => {
  it('returns the entering stack when no tags present', () => {
    expect(scanSegment('plain text', ['whisper'])).toEqual(['whisper'])
  })

  it('pushes an open tag', () => {
    expect(scanSegment('<whisper>hi', [])).toEqual(['whisper'])
  })

  it('pops a matching close tag', () => {
    expect(scanSegment('hi</whisper>', ['whisper'])).toEqual([])
  })

  it('handles balanced nesting', () => {
    expect(scanSegment('<soft><emphasis>word</emphasis></soft>', [])).toEqual([])
  })

  it('ignores non-canonical tags (treats as plain text)', () => {
    expect(scanSegment('<foo>hi</foo>', [])).toEqual([])
  })

  it('ignores underflow pops (LLM error, passes through)', () => {
    expect(scanSegment('</whisper>hi', [])).toEqual([])
  })

  it('keeps later closes that do not match the top', () => {
    expect(scanSegment('</emphasis>', ['soft'])).toEqual(['soft'])
  })
})

describe('wrapSegmentWithActiveStack', () => {
  it('passes text through unchanged when both stacks are empty', () => {
    expect(wrapSegmentWithActiveStack('hello.', [], [])).toBe('hello.')
  })

  it('prepends opens for the entering stack in stack order', () => {
    expect(wrapSegmentWithActiveStack('hi', ['soft', 'emphasis'], ['soft', 'emphasis']))
      .toBe('<soft><emphasis>hi</emphasis></soft>')
  })

  it('appends closes for the leaving stack in reverse order', () => {
    expect(wrapSegmentWithActiveStack('hi', ['soft'], ['soft', 'emphasis']))
      .toBe('<soft>hi</emphasis></soft>')
  })

  it('omits no-longer-active wraps on exit', () => {
    expect(wrapSegmentWithActiveStack('hi</emphasis>', ['soft', 'emphasis'], ['soft']))
      .toBe('<soft><emphasis>hi</emphasis></soft>')
  })

  it('preserves interior tags as authored by the LLM', () => {
    expect(wrapSegmentWithActiveStack('a <whisper>b</whisper> c', [], []))
      .toBe('a <whisper>b</whisper> c')
  })
})
