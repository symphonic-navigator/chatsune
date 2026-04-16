/**
 * Zustand store for Community Provisioning host-side state.
 *
 * Caches the list of homelabs owned by the current user and their api-keys,
 * so the page can re-render from WS events without re-fetching. REST calls
 * and event handlers push into this store; components read from it via
 * selectors. The store never owns the plaintext host-key or api-key — those
 * are shown once through one-shot reveal modals and discarded.
 */

import { create } from 'zustand'
import type { ApiKey, Homelab } from './types'

interface State {
  homelabs: Record<string, Homelab>
  apiKeysByHomelab: Record<string, Record<string, ApiKey>>
  loaded: boolean
  setHomelabs: (list: Homelab[]) => void
  upsertHomelab: (h: Homelab) => void
  removeHomelab: (id: string) => void
  setApiKeys: (homelabId: string, keys: ApiKey[]) => void
  upsertApiKey: (key: ApiKey) => void
  removeApiKey: (homelabId: string, keyId: string) => void
  setOnline: (homelabId: string, isOnline: boolean) => void
  touchLastSeen: (homelabId: string, at: string) => void
}

export const useCommunityProvisioningStore = create<State>((set) => ({
  homelabs: {},
  apiKeysByHomelab: {},
  loaded: false,

  setHomelabs: (list) =>
    set({
      homelabs: Object.fromEntries(list.map((h) => [h.homelab_id, h])),
      loaded: true,
    }),

  upsertHomelab: (h) =>
    set((s) => ({ homelabs: { ...s.homelabs, [h.homelab_id]: h } })),

  removeHomelab: (id) =>
    set((s) => {
      const homelabs = { ...s.homelabs }
      delete homelabs[id]
      const apiKeysByHomelab = { ...s.apiKeysByHomelab }
      delete apiKeysByHomelab[id]
      return { homelabs, apiKeysByHomelab }
    }),

  setApiKeys: (homelabId, keys) =>
    set((s) => ({
      apiKeysByHomelab: {
        ...s.apiKeysByHomelab,
        [homelabId]: Object.fromEntries(keys.map((k) => [k.api_key_id, k])),
      },
    })),

  upsertApiKey: (key) =>
    set((s) => ({
      apiKeysByHomelab: {
        ...s.apiKeysByHomelab,
        [key.homelab_id]: {
          ...(s.apiKeysByHomelab[key.homelab_id] ?? {}),
          [key.api_key_id]: key,
        },
      },
    })),

  removeApiKey: (homelabId, keyId) =>
    set((s) => {
      const bucket = { ...(s.apiKeysByHomelab[homelabId] ?? {}) }
      delete bucket[keyId]
      return {
        apiKeysByHomelab: { ...s.apiKeysByHomelab, [homelabId]: bucket },
      }
    }),

  setOnline: (homelabId, isOnline) =>
    set((s) => {
      const h = s.homelabs[homelabId]
      if (!h) return s
      return {
        homelabs: { ...s.homelabs, [homelabId]: { ...h, is_online: isOnline } },
      }
    }),

  touchLastSeen: (homelabId, at) =>
    set((s) => {
      const h = s.homelabs[homelabId]
      if (!h) return s
      return {
        homelabs: { ...s.homelabs, [homelabId]: { ...h, last_seen_at: at } },
      }
    }),
}))
