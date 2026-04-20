import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useProvidersStore } from './providersStore'

vi.mock('../api/providers', () => ({
  providersApi: {
    catalogue: vi.fn(),
    listAccounts: vi.fn(),
    upsertAccount: vi.fn(),
    deleteAccount: vi.fn(),
  },
}))

describe('providersStore', () => {
  beforeEach(() => {
    useProvidersStore.setState({
      catalogue: [],
      accounts: [],
      loading: false,
      error: null,
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
})
