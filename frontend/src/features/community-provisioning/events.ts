/**
 * WebSocket event → store reducer wiring for Community Provisioning.
 *
 * The backend wraps every emitted event in a BaseEvent envelope
 * (`backend/ws/event_bus.py:publish`). The envelope surfaces:
 *
 *   { type, scope, correlation_id, sequence, timestamp, payload }
 *
 * where `payload` is the Pydantic event class's full `model_dump`
 * — so the homelab/api-key domain fields live at `event.payload.*`,
 * not at the top level.
 */

import type { BaseEvent } from '../../core/types/events'
import { Topics } from '../../core/types/events'
import { useCommunityProvisioningStore } from './store'
import type { ApiKey, Homelab } from './types'

function isHomelab(value: unknown): value is Homelab {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { homelab_id?: unknown }).homelab_id === 'string'
  )
}

function isApiKey(value: unknown): value is ApiKey {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { api_key_id?: unknown }).api_key_id === 'string' &&
    typeof (value as { homelab_id?: unknown }).homelab_id === 'string'
  )
}

/**
 * Handle a single WebSocket event. Silently ignores events we don't care
 * about, and skips any event whose payload shape doesn't match the contract
 * (defensive — the backend should always match).
 */
export function handleCommunityProvisioningEvent(event: BaseEvent): void {
  const store = useCommunityProvisioningStore.getState()
  const payload = (event.payload ?? {}) as Record<string, unknown>

  switch (event.type) {
    case Topics.LLM_HOMELAB_CREATED:
    case Topics.LLM_HOMELAB_UPDATED:
    case Topics.LLM_HOMELAB_HOST_KEY_REGENERATED: {
      const h = payload.homelab
      if (isHomelab(h)) store.upsertHomelab(h)
      return
    }
    case Topics.LLM_HOMELAB_DELETED: {
      const id = payload.homelab_id
      if (typeof id === 'string') store.removeHomelab(id)
      return
    }
    case Topics.LLM_HOMELAB_STATUS_CHANGED: {
      const id = payload.homelab_id
      const online = payload.is_online
      if (typeof id === 'string' && typeof online === 'boolean') {
        store.setOnline(id, online)
      }
      return
    }
    case Topics.LLM_HOMELAB_LAST_SEEN: {
      const id = payload.homelab_id
      const seen = payload.last_seen_at
      if (typeof id === 'string' && typeof seen === 'string') {
        store.touchLastSeen(id, seen)
      }
      return
    }
    case Topics.LLM_API_KEY_CREATED:
    case Topics.LLM_API_KEY_UPDATED: {
      const key = payload.api_key
      if (isApiKey(key)) store.upsertApiKey(key)
      return
    }
    case Topics.LLM_API_KEY_REVOKED: {
      const homelabId = payload.homelab_id
      const keyId = payload.api_key_id
      if (typeof homelabId === 'string' && typeof keyId === 'string') {
        store.removeApiKey(homelabId, keyId)
      }
      return
    }
  }
}
