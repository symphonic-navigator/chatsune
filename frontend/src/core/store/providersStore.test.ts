import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useProvidersStore } from './providersStore'

vi.mock('../api/providers', () => ({
  providersApi: {
    catalogue: vi.fn(),
    listAccounts: vi.fn(),
    upsertAccount: vi.fn(),
    deleteAccount: vi.fn(),
    testAccount: vi.fn(),
  },
}))

describe('providersStore', () => {
  beforeEach(() => {
    useProvidersStore.setState({
      catalogue: [],
      accounts: [],
      loading: false,
      error: null,
      testingIds: new Set<string>(),
    })
  })

  it('computes configured ids from accounts', () => {
    useProvidersStore.setState({
      accounts: [
        {
          provider_id: 'xai',
          config: {},
          last_test_status: null,
          last_test_error: null,
          last_test_at: null,
        },
      ],
    })
    expect([...useProvidersStore.getState().configuredIds()]).toEqual(['xai'])
  })

  it('computes covered capabilities from configured accounts only', () => {
    useProvidersStore.setState({
      catalogue: [
        {
          id: 'xai',
          display_name: 'xAI',
          icon: '',
          base_url: '',
          capabilities: ['llm', 'tts'],
          config_fields: [],
          linked_integrations: [],
        },
        {
          id: 'mistral',
          display_name: 'Mistral',
          icon: '',
          base_url: '',
          capabilities: ['stt'],
          config_fields: [],
          linked_integrations: [],
        },
      ],
      accounts: [
        {
          provider_id: 'xai',
          config: {},
          last_test_status: 'ok',
          last_test_error: null,
          last_test_at: null,
        },
      ],
    })
    const covered = [...useProvidersStore.getState().coveredCapabilities()].sort()
    expect(covered).toEqual(['llm', 'tts'])
  })

  it('save upserts into accounts array', async () => {
    const { providersApi } = await import('../api/providers')
    ;(providersApi.upsertAccount as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      provider_id: 'xai',
      config: { api_key: { is_set: true } },
      last_test_status: null,
      last_test_error: null,
      last_test_at: null,
    })
    await useProvidersStore.getState().save('xai', { api_key: 'k' })
    expect(useProvidersStore.getState().accounts).toHaveLength(1)
    expect(useProvidersStore.getState().accounts[0].provider_id).toBe('xai')
  })

  it('test() flips testingIds on, calls refresh, then flips it off', async () => {
    const { providersApi } = await import('../api/providers')
    ;(providersApi.testAccount as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      status: 'ok',
      error: null,
    })
    // Stub out the refresh() side-effect calls.
    ;(providersApi.catalogue as ReturnType<typeof vi.fn>).mockResolvedValueOnce([])
    ;(providersApi.listAccounts as ReturnType<typeof vi.fn>).mockResolvedValueOnce([])

    const started = useProvidersStore.getState().test('xai')
    // Synchronously after calling test(), the id must already be in the set.
    expect(useProvidersStore.getState().testingIds.has('xai')).toBe(true)

    await started

    expect(useProvidersStore.getState().testingIds.has('xai')).toBe(false)
    expect(providersApi.testAccount).toHaveBeenCalledWith('xai')
    expect(providersApi.listAccounts).toHaveBeenCalled() // refresh ran
  })

  it('test() clears testingIds even when the API call throws', async () => {
    const { providersApi } = await import('../api/providers')
    ;(providersApi.testAccount as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('network down'),
    )

    await expect(useProvidersStore.getState().test('xai')).rejects.toThrow(
      'network down',
    )
    expect(useProvidersStore.getState().testingIds.has('xai')).toBe(false)
  })
})
