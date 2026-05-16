import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  Connection,
  ModelMetaDto,
  UserModelConfigDto,
} from '../../types/llm'
import type {
  PremiumProviderAccount,
  PremiumProviderDefinition,
} from '../../types/providers'

vi.mock('../../api/llm', () => ({
  llmApi: {
    listConnections: vi.fn(),
    listUserModelConfigs: vi.fn(),
    listConnectionModels: vi.fn(),
  },
}))

vi.mock('../../api/providers', () => ({
  providersApi: {
    catalogue: vi.fn(),
    listAccounts: vi.fn(),
    listProviderModels: vi.fn(),
  },
}))

vi.mock('../../websocket/eventBus', () => ({
  eventBus: { on: vi.fn(() => () => {}) },
}))

import { llmApi } from '../../api/llm'
import { providersApi } from '../../api/providers'
import { useEnrichedModels } from '../useEnrichedModels'

function makeConn(id: string, slug: string, createdAt: string): Connection {
  return {
    id,
    user_id: 'u',
    adapter_type: 'ollama_http',
    display_name: slug,
    slug,
    config: {},
    last_test_status: 'valid',
    last_test_error: null,
    last_test_at: null,
    created_at: createdAt,
    updated_at: createdAt,
    is_system_managed: false,
  }
}

function makeModel(uid: string, name: string): ModelMetaDto {
  return {
    connection_id: uid.split(':')[0],
    connection_slug: uid.split(':')[0],
    connection_display_name: uid.split(':')[0],
    model_id: uid.split(':').slice(1).join(':'),
    display_name: name,
    context_window: 8000,
    supports_reasoning: false,
    supports_vision: false,
    supports_tool_calls: false,
    reasoning: { kind: 'no_reasoning', effort: null, default_on: false },
    tools: { supported: false, exclusive_with_reasoning: false },
    first_class_support: false,
    parameter_count: null,
    raw_parameter_count: null,
    quantisation_level: null,
    unique_id: uid,
  }
}

function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

beforeEach(() => {
  vi.clearAllMocks()
  ;(llmApi.listConnections as ReturnType<typeof vi.fn>).mockResolvedValue([])
  ;(llmApi.listUserModelConfigs as ReturnType<typeof vi.fn>).mockResolvedValue([] as UserModelConfigDto[])
  ;(llmApi.listConnectionModels as ReturnType<typeof vi.fn>).mockResolvedValue([])
  ;(providersApi.catalogue as ReturnType<typeof vi.fn>).mockResolvedValue([] as PremiumProviderDefinition[])
  ;(providersApi.listAccounts as ReturnType<typeof vi.fn>).mockResolvedValue([] as PremiumProviderAccount[])
  ;(providersApi.listProviderModels as ReturnType<typeof vi.fn>).mockResolvedValue([])
})

describe('useEnrichedModels — baseline', () => {
  it('returns ready groups with models for each connection', async () => {
    ;(llmApi.listConnections as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeConn('c1', 'one', '2026-05-01T00:00:00Z'),
    ])
    ;(llmApi.listConnectionModels as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeModel('c1:m1', 'Model M1'),
    ])

    const { result } = renderHook(() => useEnrichedModels())

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.groups).toHaveLength(1)
    expect(result.current.groups[0].connection.id).toBe('c1')
    expect(result.current.groups[0].status).toBe('ready')
    expect(result.current.groups[0].models).toHaveLength(1)
    expect(result.current.groups[0].models[0].display_name).toBe('Model M1')
  })
})

describe('useEnrichedModels — phase A', () => {
  it('commits group skeleton before any model fetch resolves', async () => {
    ;(llmApi.listConnections as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeConn('c1', 'one', '2026-05-01T00:00:00Z'),
      makeConn('c2', 'two', '2026-05-02T00:00:00Z'),
    ])

    const heldOne = deferred<ModelMetaDto[]>()
    const heldTwo = deferred<ModelMetaDto[]>()
    ;(llmApi.listConnectionModels as ReturnType<typeof vi.fn>).mockImplementation(
      (id: string) => (id === 'c1' ? heldOne.promise : heldTwo.promise),
    )

    const { result } = renderHook(() => useEnrichedModels())

    await waitFor(() => expect(result.current.groups).toHaveLength(2))

    expect(result.current.groups[0].connection.id).toBe('c1')
    expect(result.current.groups[0].status).toBe('loading')
    expect(result.current.groups[0].models).toHaveLength(0)
    expect(result.current.groups[1].status).toBe('loading')

    await act(async () => {
      heldOne.resolve([])
      heldTwo.resolve([])
    })
  })
})

describe('useEnrichedModels — phase B ready', () => {
  it('writes ready status and models for one group while another is still loading', async () => {
    ;(llmApi.listConnections as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeConn('c1', 'one', '2026-05-01T00:00:00Z'),
      makeConn('c2', 'two', '2026-05-02T00:00:00Z'),
    ])

    const slow = deferred<ModelMetaDto[]>()
    ;(llmApi.listConnectionModels as ReturnType<typeof vi.fn>).mockImplementation(
      async (id: string) => (id === 'c1' ? [makeModel('c1:m1', 'Fast')] : slow.promise),
    )

    const { result } = renderHook(() => useEnrichedModels())

    await waitFor(() =>
      expect(result.current.groups.find((g) => g.connection.id === 'c1')?.status)
        .toBe('ready'),
    )

    const fast = result.current.groups.find((g) => g.connection.id === 'c1')!
    expect(fast.models).toHaveLength(1)
    expect(fast.models[0].display_name).toBe('Fast')

    const slowGroup = result.current.groups.find((g) => g.connection.id === 'c2')!
    expect(slowGroup.status).toBe('loading')
    expect(slowGroup.models).toHaveLength(0)

    await act(async () => { slow.resolve([]) })
  })
})

describe('useEnrichedModels — phase B error', () => {
  it('marks a single group as error without affecting siblings', async () => {
    ;(llmApi.listConnections as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeConn('c1', 'one', '2026-05-01T00:00:00Z'),
      makeConn('c2', 'two', '2026-05-02T00:00:00Z'),
    ])
    ;(llmApi.listConnectionModels as ReturnType<typeof vi.fn>).mockImplementation(
      async (id: string) => {
        if (id === 'c1') return [makeModel('c1:m1', 'Ok')]
        throw new Error('upstream 503')
      },
    )

    const { result } = renderHook(() => useEnrichedModels())

    await waitFor(() =>
      expect(result.current.groups.find((g) => g.connection.id === 'c2')?.status)
        .toBe('error'),
    )

    const bad = result.current.groups.find((g) => g.connection.id === 'c2')!
    expect(bad.error).toContain('upstream 503')
    expect(bad.models).toHaveLength(0)

    const ok = result.current.groups.find((g) => g.connection.id === 'c1')!
    expect(ok.status).toBe('ready')
    expect(ok.models).toHaveLength(1)
  })
})

describe('useEnrichedModels — loading settle gate', () => {
  it('keeps loading true while any group is still fetching, flips false once all settled', async () => {
    ;(llmApi.listConnections as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeConn('c1', 'one', '2026-05-01T00:00:00Z'),
    ])
    const held = deferred<ModelMetaDto[]>()
    ;(llmApi.listConnectionModels as ReturnType<typeof vi.fn>).mockReturnValue(held.promise)

    const { result } = renderHook(() => useEnrichedModels())

    await waitFor(() => expect(result.current.groups).toHaveLength(1))
    // Group skeleton committed but model fetch still in flight.
    expect(result.current.loading).toBe(true)

    await act(async () => {
      held.resolve([makeModel('c1:m1', 'Done')])
    })

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.groups[0].status).toBe('ready')
  })
})

describe('useEnrichedModels — stale write guard', () => {
  it('drops a per-group write from a superseded refresh', async () => {
    ;(llmApi.listConnections as ReturnType<typeof vi.fn>).mockResolvedValue([
      makeConn('c1', 'one', '2026-05-01T00:00:00Z'),
    ])

    const firstHeld = deferred<ModelMetaDto[]>()
    const secondModels = [makeModel('c1:fresh', 'Fresh')]
    const calls: Array<{ id: string }> = []
    ;(llmApi.listConnectionModels as ReturnType<typeof vi.fn>).mockImplementation(
      async (id: string) => {
        calls.push({ id })
        return calls.length === 1 ? firstHeld.promise : secondModels
      },
    )

    const { result } = renderHook(() => useEnrichedModels())
    await waitFor(() => expect(result.current.groups).toHaveLength(1))

    // Trigger a second refresh that will resolve before the first.
    await act(async () => { await result.current.refresh() })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.groups[0].models[0].display_name).toBe('Fresh')

    // Now let the first refresh's held fetch resolve with stale data.
    await act(async () => {
      firstHeld.resolve([makeModel('c1:stale', 'Stale')])
    })

    // State must still reflect the second refresh, not the late stale write.
    expect(result.current.groups[0].models[0].display_name).toBe('Fresh')
    expect(result.current.groups[0].status).toBe('ready')
  })
})
