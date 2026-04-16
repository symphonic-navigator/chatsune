/**
 * WebSocket event → store reducer wiring for Community Provisioning.
 *
 * The backend emits `llm.homelab.*` and `llm.api_key.*` events through the
 * shared WebSocket. Event bodies are FLAT (no `payload` wrapper) — fields
 * live directly on the event object, matching the rest of Chatsune's LLM
 * events (see `shared/events/llm.py`).
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
  const e = event as unknown as Record<string, unknown>

  switch (event.type) {
    case Topics.LLM_HOMELAB_CREATED:
    case Topics.LLM_HOMELAB_UPDATED:
    case Topics.LLM_HOMELAB_HOST_KEY_REGENERATED: {
      const h = e.homelab
      if (isHomelab(h)) store.upsertHomelab(h)
      return
    }
    case Topics.LLM_HOMELAB_DELETED: {
      const id = e.homelab_id
      if (typeof id === 'string') store.removeHomelab(id)
      return
    }
    case Topics.LLM_HOMELAB_STATUS_CHANGED: {
      const id = e.homelab_id
      const online = e.is_online
      if (typeof id === 'string' && typeof online === 'boolean') {
        store.setOnline(id, online)
      }
      return
    }
    case Topics.LLM_HOMELAB_LAST_SEEN: {
      const id = e.homelab_id
      const seen = e.last_seen_at
      if (typeof id === 'string' && typeof seen === 'string') {
        store.touchLastSeen(id, seen)
      }
      return
    }
    case Topics.LLM_API_KEY_CREATED:
    case Topics.LLM_API_KEY_UPDATED: {
      const key = e.api_key
      if (isApiKey(key)) store.upsertApiKey(key)
      return
    }
    case Topics.LLM_API_KEY_REVOKED: {
      const homelabId = e.homelab_id
      const keyId = e.api_key_id
      if (typeof homelabId === 'string' && typeof keyId === 'string') {
        store.removeApiKey(homelabId, keyId)
      }
      return
    }
  }
}
