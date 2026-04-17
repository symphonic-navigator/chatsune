import { beforeEach, describe, expect, it } from 'vitest'
import { useCommunityProvisioningStore } from '../store'
import type { ApiKey, Homelab } from '../types'

function makeHomelab(overrides: Partial<Homelab> = {}): Homelab {
  return {
    homelab_id: 'h1',
    display_name: 'Home Lab 1',
    host_key_hint: 'ab12',
    status: 'active',
    created_at: '2026-04-16T10:00:00Z',
    last_seen_at: null,
    last_sidecar_version: null,
    last_engine_info: null,
    is_online: false,
    max_concurrent_requests: 3,
    host_slug: 'home-lab-1',
    ...overrides,
  }
}

function makeApiKey(overrides: Partial<ApiKey> = {}): ApiKey {
  return {
    api_key_id: 'k1',
    homelab_id: 'h1',
    display_name: 'Key 1',
    api_key_hint: 'xy34',
    allowed_model_slugs: [],
    status: 'active',
    created_at: '2026-04-16T10:00:00Z',
    revoked_at: null,
    last_used_at: null,
    max_concurrent: 1,
    ...overrides,
  }
}

describe('useCommunityProvisioningStore', () => {
  beforeEach(() => {
    useCommunityProvisioningStore.setState({
      homelabs: {},
      apiKeysByHomelab: {},
      loaded: false,
    })
  })

  it('setHomelabs populates the keyed map and flips loaded', () => {
    const { setHomelabs } = useCommunityProvisioningStore.getState()
    setHomelabs([makeHomelab({ homelab_id: 'a' }), makeHomelab({ homelab_id: 'b' })])
    const s = useCommunityProvisioningStore.getState()
    expect(Object.keys(s.homelabs).sort()).toEqual(['a', 'b'])
    expect(s.loaded).toBe(true)
  })

  it('upsertHomelab adds and replaces by id', () => {
    const { upsertHomelab } = useCommunityProvisioningStore.getState()
    upsertHomelab(makeHomelab({ homelab_id: 'h1', display_name: 'First' }))
    upsertHomelab(makeHomelab({ homelab_id: 'h1', display_name: 'Renamed' }))
    expect(useCommunityProvisioningStore.getState().homelabs['h1'].display_name).toBe('Renamed')
  })

  it('removeHomelab also drops its api-key bucket', () => {
    const { upsertHomelab, setApiKeys, removeHomelab } =
      useCommunityProvisioningStore.getState()
    upsertHomelab(makeHomelab({ homelab_id: 'h1' }))
    setApiKeys('h1', [makeApiKey()])
    removeHomelab('h1')
    const s = useCommunityProvisioningStore.getState()
    expect(s.homelabs['h1']).toBeUndefined()
    expect(s.apiKeysByHomelab['h1']).toBeUndefined()
  })

  it('upsertApiKey slots the key under its homelab bucket', () => {
    const { upsertApiKey } = useCommunityProvisioningStore.getState()
    upsertApiKey(makeApiKey({ homelab_id: 'h1', api_key_id: 'k1' }))
    upsertApiKey(makeApiKey({ homelab_id: 'h1', api_key_id: 'k2' }))
    const bucket = useCommunityProvisioningStore.getState().apiKeysByHomelab['h1']
    expect(Object.keys(bucket).sort()).toEqual(['k1', 'k2'])
  })

  it('removeApiKey removes only that one key', () => {
    const { upsertApiKey, removeApiKey } =
      useCommunityProvisioningStore.getState()
    upsertApiKey(makeApiKey({ api_key_id: 'k1' }))
    upsertApiKey(makeApiKey({ api_key_id: 'k2' }))
    removeApiKey('h1', 'k1')
    const bucket = useCommunityProvisioningStore.getState().apiKeysByHomelab['h1']
    expect(Object.keys(bucket)).toEqual(['k2'])
  })

  it('setOnline patches is_online without touching other fields', () => {
    const { upsertHomelab, setOnline } = useCommunityProvisioningStore.getState()
    upsertHomelab(makeHomelab({ homelab_id: 'h1', display_name: 'Keep' }))
    setOnline('h1', true)
    const h = useCommunityProvisioningStore.getState().homelabs['h1']
    expect(h.is_online).toBe(true)
    expect(h.display_name).toBe('Keep')
  })

  it('setOnline is a no-op when the homelab is unknown', () => {
    const { setOnline } = useCommunityProvisioningStore.getState()
    setOnline('nope', true)
    expect(useCommunityProvisioningStore.getState().homelabs).toEqual({})
  })

  it('touchLastSeen updates last_seen_at', () => {
    const { upsertHomelab, touchLastSeen } =
      useCommunityProvisioningStore.getState()
    upsertHomelab(makeHomelab({ homelab_id: 'h1' }))
    touchLastSeen('h1', '2026-04-16T12:00:00Z')
    expect(useCommunityProvisioningStore.getState().homelabs['h1'].last_seen_at).toBe(
      '2026-04-16T12:00:00Z',
    )
  })
})
