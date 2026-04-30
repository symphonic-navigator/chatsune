import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore } from '../../../core/store/chatStore'
import type { ChatMessageDto } from '../../../core/api/chat'

/*
 * Regression tests for the per-message pill-content cache.
 *
 * When a streamed assistant message contains an inline-trigger tag (e.g.
 * `<screen_effect rising_emojis 💖>`), the live buffer rewrites the tag to a
 * placeholder in `streamingContent` and mutates the active Group's
 * `renderedPillsMap` with `effectId → pillContent`. At stream end the
 * persisted message's `content` field carries the placeholder — NOT the raw
 * tag — so a fresh `ResponseTagBuffer` over that content alone produces an
 * empty pill map and the pill disappears.
 *
 * The fix: `finishStreaming` accepts an optional `pillContents` map and
 * stores it under `messagePillContents[messageId]`. `AssistantMessage` reads
 * this cache on the persisted-render path so the pill survives stream-end.
 *
 * After F5 / history-load the cache is empty for old messages, and the
 * persisted-render path (which sees raw tags from the backend) takes over.
 */

function makeMessage(id: string, content: string): ChatMessageDto {
  return {
    id,
    session_id: 's1',
    role: 'assistant',
    content,
    thinking: null,
    token_count: 0,
    attachments: null,
    web_search_context: null,
    knowledge_context: null,
    events: null,
    refusal_text: null,
    created_at: '2026-04-30T00:00:00Z',
    status: 'completed',
    time_to_first_token_ms: null,
    tokens_per_second: null,
    generation_duration_ms: null,
    provider_name: null,
    model_name: null,
  }
}

describe('persisted pill cache', () => {
  beforeEach(() => {
    useChatStore.getState().reset()
  })

  it('caches the live pill map on stream end', () => {
    const pillsMap = new Map<string, string>([
      ['abc-uuid', '✨ rising_emojis 💖🤘🔥'],
    ])
    useChatStore.getState().finishStreaming(
      makeMessage('msg-1', 'Hi! ​[effect:abc-uuid]​'),
      'green',
      0,
      0,
      0,
      pillsMap,
    )
    const cached = useChatStore.getState().messagePillContents['msg-1']
    expect(cached).toBeDefined()
    expect(cached.get('abc-uuid')).toBe('✨ rising_emojis 💖🤘🔥')
  })

  it('does not cache an empty pill map (plain-text messages stay lean)', () => {
    useChatStore.getState().finishStreaming(
      makeMessage('msg-2', 'Plain text only.'),
      'green',
      0,
      0,
      0,
      new Map(),
    )
    expect(useChatStore.getState().messagePillContents['msg-2']).toBeUndefined()
  })

  it('does not cache when no pillContents argument is supplied', () => {
    useChatStore.getState().finishStreaming(
      makeMessage('msg-3', 'No pills'),
      'green',
      0,
      0,
      0,
    )
    expect(useChatStore.getState().messagePillContents['msg-3']).toBeUndefined()
  })

  it('clears cache entries when their message is deleted', () => {
    const pillsMap = new Map<string, string>([['uuid-x', 'content-x']])
    useChatStore.getState().finishStreaming(
      makeMessage('msg-4', 'Hi ​[effect:uuid-x]​'),
      'green',
      0,
      0,
      0,
      pillsMap,
    )
    expect(useChatStore.getState().messagePillContents['msg-4']).toBeDefined()
    useChatStore.getState().deleteMessage('msg-4')
    expect(useChatStore.getState().messagePillContents['msg-4']).toBeUndefined()
  })

  it('moves cache entry on swapMessageId', () => {
    const pillsMap = new Map<string, string>([['uuid-y', 'content-y']])
    // Seed the cache as if finishStreaming had run with the optimistic id.
    useChatStore.setState({
      messagePillContents: { 'optimistic-1': pillsMap },
      messages: [makeMessage('optimistic-1', 'Hi ​[effect:uuid-y]​')],
    })
    useChatStore.getState().swapMessageId('optimistic-1', 'real-1')
    const cache = useChatStore.getState().messagePillContents
    expect(cache['optimistic-1']).toBeUndefined()
    expect(cache['real-1']).toBe(pillsMap)
  })

  it('drops cache entries for messages removed by truncateAfter', () => {
    const pillsA = new Map<string, string>([['ua', 'a']])
    const pillsB = new Map<string, string>([['ub', 'b']])
    useChatStore.setState({
      messages: [
        makeMessage('m1', 'a'),
        makeMessage('m2', 'b'),
        makeMessage('m3', 'c'),
      ],
      messagePillContents: { m1: pillsA, m2: pillsB },
    })
    useChatStore.getState().truncateAfter('m1')
    const cache = useChatStore.getState().messagePillContents
    expect(cache['m1']).toBe(pillsA)
    expect(cache['m2']).toBeUndefined()
  })
})
