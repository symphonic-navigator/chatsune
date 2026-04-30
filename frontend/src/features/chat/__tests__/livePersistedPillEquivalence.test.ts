import { describe, it, expect, beforeEach, vi } from 'vitest'
import { unified } from 'unified'
import rehypeParse from 'rehype-parse'
import rehypeStringify from 'rehype-stringify'
import rehypeIntegrationPills from '../rehypeIntegrationPills'
import type { TagExecutionResult } from '../../integrations/types'
import type { PendingEffect } from '../../integrations/responseTagProcessor'

/*
 * Live-vs-persisted pill equivalence regression test.
 *
 * Two paths in AssistantMessage feed `rehypeIntegrationPills`:
 *
 *   - LIVE     — buffer runs in `live_stream` mode while tokens stream in;
 *                its `renderedPillsMap` is the source of truth and side
 *                effects fire (`runSideEffects: true`).
 *   - PERSISTED — buffer runs once in `text_only` mode after the message is
 *                 stored; its `renderedPillsMap` feeds the rehype plugin and
 *                 side effects MUST NOT fire (`runSideEffects: false`).
 *
 * Both paths must produce identical pill DOM for the same raw tag, otherwise
 * a streaming pill would differ from the same message after a page reload.
 * This test asserts:
 *
 *   1. Both buffers produce the same pill content string for the same tag.
 *   2. The rehype plugin emits the same DOM when fed either path's map.
 *   3. The persisted path NEVER invokes the plugin's `sideEffect` thunk.
 */

const ZWSP = '​'
const PLACEHOLDER_RE = new RegExp(`${ZWSP}\\[effect:([^\\]]+)\\]${ZWSP}`)

function renderPills(content: string, pillContents: Map<string, string>): string {
  return unified()
    .use(rehypeParse, { fragment: true })
    .use(rehypeIntegrationPills, { pillContents })
    .use(rehypeStringify)
    .processSync(`<p>${content}</p>`)
    .toString()
}

interface MockPlugin {
  executeTag: (
    command: string,
    args: string[],
    config: Record<string, unknown>,
  ) => TagExecutionResult
}

async function withMocks(
  plugin: MockPlugin,
  testFn: (mod: typeof import('../../integrations/responseTagProcessor')) => Promise<void>,
): Promise<void> {
  vi.resetModules()
  vi.doMock('../../integrations/registry', () => ({
    getPlugin: (_id: string) => plugin,
  }))
  vi.doMock('../../integrations/store', () => ({
    useIntegrationsStore: {
      getState: () => ({
        definitions: [
          { id: 'lovense', has_response_tags: true },
          { id: 'screen_effect', has_response_tags: true },
        ],
        getConfig: (_id: string) => undefined,
      }),
    },
  }))
  const mod = await import('../../integrations/responseTagProcessor')
  await testFn(mod)
}

beforeEach(() => {
  vi.resetModules()
  vi.clearAllMocks()
})

describe('live vs persisted pill equivalence', () => {
  it('produces identical pill DOM for the same tag in both paths', async () => {
    const sideEffect = vi.fn(() => Promise.resolve())
    const executeTag = (
      cmd: string,
      args: string[],
      _cfg: Record<string, unknown>,
    ): TagExecutionResult => ({
      // The buffer hands `cmd = "vibrate"` and `args = ["5"]` to the plugin
      // for the tag `<lovense vibrate 5>` (the integration id is consumed by
      // the buffer itself before plugin dispatch).
      pillContent: `${cmd} at ${args[0] ?? ''}`,
      syncWithTts: false,
      effectPayload: { kind: 'demo' },
      sideEffect,
    })

    await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
      const rawTag = '<lovense vibrate 5>'

      // LIVE path: side effects ON, source = live_stream.
      const livePending = new Map<string, PendingEffect>()
      const livePills = new Map<string, string>()
      const liveBuffer = new ResponseTagBuffer(
        () => undefined,
        'live_stream',
        livePending,
        () => undefined,
        livePills,
        // runSideEffects defaults to true — explicit for clarity.
        { runSideEffects: true },
      )
      const liveOut = liveBuffer.process(rawTag)

      // PERSISTED path: side effects OFF, source = text_only.
      const persistedPending = new Map<string, PendingEffect>()
      const persistedPills = new Map<string, string>()
      const persistedBuffer = new ResponseTagBuffer(
        () => undefined,
        'text_only',
        persistedPending,
        () => undefined,
        persistedPills,
        { runSideEffects: false },
      )
      const persistedOut = persistedBuffer.process(rawTag)

      // 1. Same pill content string in both maps.
      expect(livePills.size).toBe(1)
      expect(persistedPills.size).toBe(1)
      const livePillContent = [...livePills.values()][0]
      const persistedPillContent = [...persistedPills.values()][0]
      expect(livePillContent).toBe(persistedPillContent)
      expect(livePillContent).toBe('vibrate at 5')

      // 2. Both outputs are placeholders (UUIDs differ by design).
      expect(liveOut).toMatch(PLACEHOLDER_RE)
      expect(persistedOut).toMatch(PLACEHOLDER_RE)

      // 3. Rehype DOM is identical when fed either path's map. Normalise the
      //    placeholder UUIDs to a fixed sentinel before rendering so the two
      //    inputs are byte-identical — what we are asserting is that the
      //    pill content (the load-bearing invariant) round-trips identically
      //    through the rehype pipeline.
      const liveId = [...livePills.keys()][0]
      const persistedId = [...persistedPills.keys()][0]
      const SENTINEL = '00000000-0000-4000-8000-000000000000'
      const liveNormalised = liveOut.replace(liveId, SENTINEL)
      const persistedNormalised = persistedOut.replace(persistedId, SENTINEL)
      expect(liveNormalised).toBe(persistedNormalised)

      const liveDom = renderPills(liveNormalised, new Map([[SENTINEL, livePillContent]]))
      const persistedDom = renderPills(
        persistedNormalised,
        new Map([[SENTINEL, persistedPillContent]]),
      )
      expect(liveDom).toBe(persistedDom)
      expect(liveDom).toContain(
        '<span class="integration-pill">vibrate at 5</span>',
      )

      // 4. Side effect MUST fire on the live path and MUST NOT fire on the
      //    persisted path. This is the whole reason `runSideEffects` exists.
      expect(sideEffect).toHaveBeenCalledTimes(1)
    })
  })

  it('keeps maps consistent for multiple tags in one stream', async () => {
    const sideEffect = vi.fn(() => Promise.resolve())
    const executeTag = (
      cmd: string,
      args: string[],
      _cfg: Record<string, unknown>,
    ): TagExecutionResult => ({
      pillContent: `${cmd} at ${args[0] ?? ''}`,
      syncWithTts: false,
      effectPayload: {},
      sideEffect,
    })

    await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
      const stream = 'first <lovense vibrate 3> middle <lovense vibrate 7> end'

      const livePills = new Map<string, string>()
      const liveBuffer = new ResponseTagBuffer(
        () => undefined,
        'live_stream',
        new Map(),
        () => undefined,
        livePills,
        { runSideEffects: true },
      )
      liveBuffer.process(stream)

      const persistedPills = new Map<string, string>()
      const persistedBuffer = new ResponseTagBuffer(
        () => undefined,
        'text_only',
        new Map(),
        () => undefined,
        persistedPills,
        { runSideEffects: false },
      )
      persistedBuffer.process(stream)

      const liveValues = [...livePills.values()].sort()
      const persistedValues = [...persistedPills.values()].sort()
      expect(liveValues).toEqual(persistedValues)
      expect(liveValues).toEqual(['vibrate at 3', 'vibrate at 7'])

      // Live fires both side effects; persisted fires none.
      expect(sideEffect).toHaveBeenCalledTimes(2)
    })
  })

  it('produces identical pill DOM for a screen_effect tag in both paths', async () => {
    const { executeTag: realExecuteTag } = await import(
      '../../integrations/plugins/screen_effects/tags'
    )
    const executeTag = (
      cmd: string,
      args: string[],
      cfg: Record<string, unknown>,
    ): TagExecutionResult => realExecuteTag(cmd, args, cfg)

    await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
      const rawTag = '<screen_effect rising_emojis 💖 🤘 🔥>'

      // LIVE path: side effects ON, source = live_stream.
      const livePending = new Map<string, PendingEffect>()
      const livePills = new Map<string, string>()
      const liveBuffer = new ResponseTagBuffer(
        () => undefined,
        'live_stream',
        livePending,
        () => undefined,
        livePills,
        { runSideEffects: true },
      )
      const liveOut = liveBuffer.process(rawTag)

      // PERSISTED path: side effects OFF, source = text_only.
      const persistedPending = new Map<string, PendingEffect>()
      const persistedPills = new Map<string, string>()
      const persistedBuffer = new ResponseTagBuffer(
        () => undefined,
        'text_only',
        persistedPending,
        () => undefined,
        persistedPills,
        { runSideEffects: false },
      )
      const persistedOut = persistedBuffer.process(rawTag)

      // 1. Same pill content string in both maps.
      expect(livePills.size).toBe(1)
      expect(persistedPills.size).toBe(1)
      const livePillContent = [...livePills.values()][0]
      const persistedPillContent = [...persistedPills.values()][0]
      expect(livePillContent).toBe(persistedPillContent)
      expect(livePillContent).toBe('✨ rising_emojis 💖🤘🔥')

      // 2. Both outputs are placeholders (UUIDs differ by design).
      expect(liveOut).toMatch(PLACEHOLDER_RE)
      expect(persistedOut).toMatch(PLACEHOLDER_RE)

      // 3. Rehype DOM is identical when fed either path's map after
      //    placeholder UUIDs are normalised to a fixed sentinel.
      const liveId = [...livePills.keys()][0]
      const persistedId = [...persistedPills.keys()][0]
      const SENTINEL = '00000000-0000-4000-8000-000000000000'
      const liveNormalised = liveOut.replace(liveId, SENTINEL)
      const persistedNormalised = persistedOut.replace(persistedId, SENTINEL)
      expect(liveNormalised).toBe(persistedNormalised)

      const liveDom = renderPills(
        liveNormalised,
        new Map([[SENTINEL, livePillContent]]),
      )
      const persistedDom = renderPills(
        persistedNormalised,
        new Map([[SENTINEL, persistedPillContent]]),
      )
      expect(liveDom).toBe(persistedDom)
      expect(liveDom).toContain(
        '<span class="integration-pill">✨ rising_emojis 💖🤘🔥</span>',
      )

      // 4. screen_effect plugin has no sideEffect, so there is nothing to
      //    assert about side-effect invocation. The lovense test covers the
      //    runSideEffects flag separately.
    })
  })
})
