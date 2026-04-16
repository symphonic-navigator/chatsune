import { beforeEach, describe, expect, it } from 'vitest'
import type { BaseEvent } from '../../../core/types/events'
import { handleCommunityProvisioningEvent } from '../events'
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

function event(type: string, payload: Record<string, unknown>): BaseEvent {
  // The backend wraps every event in a BaseEvent envelope — domain fields
  // live under `payload`, not at the top level. See
  // backend/ws/event_bus.py::publish.
  return {
    id: 'e1',
    type,
    sequence: '1',
    scope: 'global',
    correlation_id: 'c1',
    timestamp: '2026-04-16T10:00:00Z',
    payload,
  }
}

describe('handleCommunityProvisioningEvent', () => {
  beforeEach(() => {
    useCommunityProvisioningStore.setState({
      homelabs: {},
      apiKeysByHomelab: {},
      loaded: false,
    })
  })

  it('llm.homelab.created upserts the homelab', () => {
    handleCommunityProvisioningEvent(
      event('llm.homelab.created', { homelab: makeHomelab({ homelab_id: 'x' }) }),
    )
    expect(useCommunityProvisioningStore.getState().homelabs['x']).toBeDefined()
  })

  it('llm.homelab.updated upserts the homelab', () => {
    handleCommunityProvisioningEvent(
      event('llm.homelab.updated', {
        homelab: makeHomelab({ homelab_id: 'x', display_name: 'New Name' }),
      }),
    )
    expect(useCommunityProvisioningStore.getState().homelabs['x'].display_name).toBe(
      'New Name',
    )
  })

  it('llm.homelab.deleted removes the homelab', () => {
    useCommunityProvisioningStore.getState().upsertHomelab(makeHomelab({ homelab_id: 'x' }))
    handleCommunityProvisioningEvent(
      event('llm.homelab.deleted', { homelab_id: 'x' }),
    )
    expect(useCommunityProvisioningStore.getState().homelabs['x']).toBeUndefined()
  })

  it('llm.homelab.status_changed patches is_online', () => {
    useCommunityProvisioningStore.getState().upsertHomelab(makeHomelab({ homelab_id: 'x' }))
    handleCommunityProvisioningEvent(
      event('llm.homelab.status_changed', { homelab_id: 'x', is_online: true }),
    )
    expect(useCommunityProvisioningStore.getState().homelabs['x'].is_online).toBe(true)
  })

  it('llm.homelab.last_seen updates last_seen_at', () => {
    useCommunityProvisioningStore.getState().upsertHomelab(makeHomelab({ homelab_id: 'x' }))
    handleCommunityProvisioningEvent(
      event('llm.homelab.last_seen', {
        homelab_id: 'x',
        last_seen_at: '2026-04-16T12:00:00Z',
      }),
    )
    expect(
      useCommunityProvisioningStore.getState().homelabs['x'].last_seen_at,
    ).toBe('2026-04-16T12:00:00Z')
  })

  it('llm.api_key.created upserts the api-key', () => {
    handleCommunityProvisioningEvent(
      event('llm.api_key.created', { api_key: makeApiKey({ api_key_id: 'k9' }) }),
    )
    expect(useCommunityProvisioningStore.getState().apiKeysByHomelab['h1']['k9']).toBeDefined()
  })

  it('llm.api_key.revoked removes the api-key', () => {
    useCommunityProvisioningStore
      .getState()
      .upsertApiKey(makeApiKey({ api_key_id: 'k9' }))
    handleCommunityProvisioningEvent(
      event('llm.api_key.revoked', { homelab_id: 'h1', api_key_id: 'k9' }),
    )
    expect(
      useCommunityProvisioningStore.getState().apiKeysByHomelab['h1']['k9'],
    ).toBeUndefined()
  })

  it('ignores unrelated event types', () => {
    handleCommunityProvisioningEvent(event('user.created', { user_id: 'x' }))
    expect(useCommunityProvisioningStore.getState().homelabs).toEqual({})
  })
})
