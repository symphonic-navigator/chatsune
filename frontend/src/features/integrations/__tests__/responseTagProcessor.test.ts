import { describe, it, expect, beforeEach, vi } from 'vitest'
import type { IntegrationInlineTrigger, TagExecutionResult } from '../types'

/*
 * Tests for ResponseTagBuffer (sync executeTag + pendingEffectsMap variant).
 *
 * Each test mocks the registry and store via `vi.doMock` because each case
 * needs its own plugin variation, and `vi.mock` would be hoisted and shared.
 *
 * The placeholder shape produced by the buffer is
 *   `​[effect:<uuid>]​`
 * where the `​` characters are zero-width spaces (the same convention
 * the legacy Lovense placeholder used).
 */

const ZWSP = '​'
// Accept any plausible id payload so we are not coupled to UUID v4 vs v7.
const PLACEHOLDER_RE = new RegExp(`${ZWSP}\\[effect:([^\\]]+)\\]${ZWSP}`)
const PLACEHOLDER_RE_GLOBAL = new RegExp(`${ZWSP}\\[effect:([^\\]]+)\\]${ZWSP}`, 'g')

interface MockPlugin {
  id?: string
  executeTag?: (
    command: string,
    args: string[],
    config: Record<string, unknown>,
  ) => TagExecutionResult
}

async function withMocks(
  plugin: MockPlugin,
  testFn: (mod: typeof import('../responseTagProcessor')) => Promise<void>,
): Promise<void> {
  vi.resetModules()

  vi.doMock('../registry', () => ({
    getPlugin: (_id: string) => plugin,
  }))

  vi.doMock('../store', () => ({
    useIntegrationsStore: {
      getState: () => ({
        definitions: [
          {
            id: 'fx',
            has_response_tags: true,
          },
        ],
        getConfig: (_id: string) => undefined,
      }),
    },
  }))

  const mod = await import('../responseTagProcessor')
  await testFn(mod)
}

beforeEach(() => {
  vi.resetModules()
  vi.clearAllMocks()
})

describe('ResponseTagBuffer', () => {
  it('replaces a detected tag with a UUID placeholder and stores it in pendingEffectsMap', async () => {
    const executeTag = vi.fn(
      (_cmd: string, _args: string[], _cfg: Record<string, unknown>): TagExecutionResult => ({
        pillContent: 'fx test',
        syncWithTts: true,
        effectPayload: { kind: 'demo' },
      }),
    )

    await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
      const onTagResolved = vi.fn()
      const pending = new Map()
      const emitTrigger = vi.fn()
      const buffer = new ResponseTagBuffer(onTagResolved, 'live_stream', pending, emitTrigger)

      const out = buffer.process('hello <fx test arg1>world')

      expect(out.startsWith('hello ')).toBe(true)
      expect(out.endsWith('world')).toBe(true)
      expect(out).toMatch(PLACEHOLDER_RE)
      expect(executeTag).toHaveBeenCalledWith('test', ['arg1'], {})
      expect(pending.size).toBe(1)
    })
  })

  it('produces distinct UUIDs for multiple occurrences of the same tag', async () => {
    const executeTag = vi.fn(
      (cmd: string): TagExecutionResult => ({
        pillContent: `fx ${cmd}`,
        syncWithTts: true,
        effectPayload: { cmd },
      }),
    )

    await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
      const buffer = new ResponseTagBuffer(
        vi.fn(),
        'live_stream',
        new Map(),
        vi.fn(),
      )

      const out = buffer.process('<fx a> and <fx b>')

      const matches = [...out.matchAll(PLACEHOLDER_RE_GLOBAL)].map((m) => m[1])
      expect(matches).toHaveLength(2)
      expect(matches[0]).not.toBe(matches[1])
    })
  })

  it('emits immediately when syncWithTts=false on a live_stream source', async () => {
    const executeTag = vi.fn(
      (): TagExecutionResult => ({
        pillContent: 'fire',
        syncWithTts: false,
        effectPayload: {},
      }),
    )

    await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
      const emitted: IntegrationInlineTrigger[] = []
      const pending = new Map()
      const buffer = new ResponseTagBuffer(
        vi.fn(),
        'live_stream',
        pending,
        (e) => emitted.push(e),
      )

      buffer.process('<fx go>')

      expect(emitted).toHaveLength(1)
      expect(emitted[0].source).toBe('live_stream')
      expect(pending.size).toBe(0)
    })
  })

  it('emits immediately when syncWithTts=true but the source is text_only', async () => {
    const executeTag = vi.fn(
      (): TagExecutionResult => ({
        pillContent: 'sync',
        syncWithTts: true,
        effectPayload: {},
      }),
    )

    await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
      const emitted: IntegrationInlineTrigger[] = []
      const pending = new Map()
      const buffer = new ResponseTagBuffer(
        vi.fn(),
        'text_only',
        pending,
        (e) => emitted.push(e),
      )

      buffer.process('<fx go>')

      expect(emitted).toHaveLength(1)
      expect(emitted[0].source).toBe('text_only')
      expect(pending.size).toBe(0)
    })
  })

  it('parks the entry in pendingEffectsMap when syncWithTts=true and source=live_stream', async () => {
    const executeTag = vi.fn(
      (): TagExecutionResult => ({
        pillContent: 'sync',
        syncWithTts: true,
        effectPayload: {},
      }),
    )

    await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
      const emitted: IntegrationInlineTrigger[] = []
      const pending = new Map()
      const buffer = new ResponseTagBuffer(
        vi.fn(),
        'live_stream',
        pending,
        (e) => emitted.push(e),
      )

      buffer.process('<fx go>')

      expect(emitted).toHaveLength(0)
      expect(pending.size).toBe(1)
    })
  })

  it('parks the entry in pendingEffectsMap when syncWithTts=true and source=read_aloud', async () => {
    const executeTag = vi.fn(
      (): TagExecutionResult => ({
        pillContent: 'sync',
        syncWithTts: true,
        effectPayload: {},
      }),
    )

    await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
      const emitted: IntegrationInlineTrigger[] = []
      const pending = new Map()
      const buffer = new ResponseTagBuffer(
        vi.fn(),
        'read_aloud',
        pending,
        (e) => emitted.push(e),
      )

      buffer.process('<fx go>')

      expect(emitted).toHaveLength(0)
      expect(pending.size).toBe(1)
    })
  })

  it('flush() emits residual pending entries', async () => {
    const executeTag = vi.fn(
      (): TagExecutionResult => ({
        pillContent: 'sync',
        syncWithTts: true,
        effectPayload: {},
      }),
    )

    await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
      const emitted: IntegrationInlineTrigger[] = []
      const pending = new Map()
      const buffer = new ResponseTagBuffer(
        vi.fn(),
        'live_stream',
        pending,
        (e) => emitted.push(e),
      )

      buffer.process('<fx go>')
      expect(pending.size).toBe(1)
      expect(emitted).toHaveLength(0)

      buffer.flush()

      expect(emitted).toHaveLength(1)
      expect(pending.size).toBe(0)
    })
  })

  it('catches a rejected sideEffect promise and still inserts the pill and emits the event', async () => {
    const executeTag = vi.fn(
      (): TagExecutionResult => ({
        pillContent: 'boom',
        syncWithTts: false,
        effectPayload: {},
        sideEffect: () => Promise.reject(new Error('boom')),
      }),
    )

    // Silence the expected console.error from the fire-and-forget catch.
    const errSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)

    try {
      await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
        const emitted: IntegrationInlineTrigger[] = []
        const pending = new Map()
        const buffer = new ResponseTagBuffer(
          vi.fn(),
          'live_stream',
          pending,
          (e) => emitted.push(e),
        )

        const out = buffer.process('<fx go>')

        expect(out).toMatch(PLACEHOLDER_RE)
        expect(emitted).toHaveLength(1)
      })

      // Allow the unhandled-rejection catch to run to completion.
      await new Promise((r) => setTimeout(r, 0))
    } finally {
      errSpy.mockRestore()
    }
  })

  it('mirrors every successful tag into renderedPillsMap, never draining it', async () => {
    const executeTag = vi.fn(
      (cmd: string): TagExecutionResult => ({
        pillContent: `fx ${cmd}`,
        syncWithTts: true,
        effectPayload: {},
      }),
    )

    await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
      const pending = new Map()
      const rendered = new Map<string, string>()
      const buffer = new ResponseTagBuffer(
        vi.fn(),
        'live_stream',
        pending,
        vi.fn(),
        rendered,
      )

      buffer.process('<fx a> <fx b>')

      // Both pill contents present in renderedPillsMap.
      const values = [...rendered.values()].sort()
      expect(values).toEqual(['fx a', 'fx b'])
      // Map identity preserved across flush — entries must NOT be drained.
      buffer.flush()
      expect(rendered.size).toBe(2)
    })
  })

  it('skips sideEffect invocation when runSideEffects=false (persisted-render mode)', async () => {
    const sideEffect = vi.fn(() => Promise.resolve())
    const executeTag = vi.fn(
      (): TagExecutionResult => ({
        pillContent: 'pill',
        syncWithTts: false,
        effectPayload: {},
        sideEffect,
      }),
    )

    await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
      const buffer = new ResponseTagBuffer(
        vi.fn(),
        'text_only',
        new Map(),
        vi.fn(),
        new Map(),
        { runSideEffects: false },
      )

      buffer.process('<fx go>')

      expect(executeTag).toHaveBeenCalledTimes(1)
      expect(sideEffect).not.toHaveBeenCalled()
    })
  })

  it('renders an error pill, emits no event, and stores no entry when executeTag throws synchronously', async () => {
    const executeTag = vi.fn((): TagExecutionResult => {
      throw new Error('kaput')
    })

    await withMocks({ executeTag }, async ({ ResponseTagBuffer }) => {
      const resolutions: Array<[string, string]> = []
      const onTagResolved = (placeholder: string, replacement: string) =>
        resolutions.push([placeholder, replacement])
      const emitted: IntegrationInlineTrigger[] = []
      const pending = new Map()
      const buffer = new ResponseTagBuffer(
        onTagResolved,
        'live_stream',
        pending,
        (e) => emitted.push(e),
      )

      buffer.process('<fx go>')

      expect(resolutions).toHaveLength(1)
      expect(resolutions[0][1]).toContain('[error:')
      expect(emitted).toHaveLength(0)
      expect(pending.size).toBe(0)
    })
  })
})
