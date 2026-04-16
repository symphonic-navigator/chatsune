/**
 * REST client for Community Provisioning endpoints.
 * Wraps the shared `api` helper from `core/api/client` so auth, refresh, and
 * error handling follow the rest of the codebase.
 */

import { api } from '../../core/api/client'
import type {
  ApiKey,
  ApiKeyCreated,
  CreateApiKeyInput,
  CreateHomelabInput,
  Homelab,
  HomelabCreated,
  HomelabHostKeyRegenerated,
  UpdateApiKeyInput,
  UpdateHomelabInput,
} from './types'

const BASE = '/api/llm/homelabs'

export const homelabsApi = {
  list: () => api.get<Homelab[]>(BASE),
  create: (body: CreateHomelabInput) => api.post<HomelabCreated>(BASE, body),
  get: (id: string) => api.get<Homelab>(`${BASE}/${id}`),
  update: (id: string, body: UpdateHomelabInput) =>
    api.patch<Homelab>(`${BASE}/${id}`, body),
  delete: (id: string) => api.delete<void>(`${BASE}/${id}`),
  regenerateHostKey: (id: string) =>
    api.post<HomelabHostKeyRegenerated>(`${BASE}/${id}/regenerate-host-key`),
}

export const apiKeysApi = {
  list: (homelabId: string) =>
    api.get<ApiKey[]>(`${BASE}/${homelabId}/api-keys`),
  create: (homelabId: string, body: CreateApiKeyInput) =>
    api.post<ApiKeyCreated>(`${BASE}/${homelabId}/api-keys`, body),
  update: (homelabId: string, keyId: string, body: UpdateApiKeyInput) =>
    api.patch<ApiKey>(`${BASE}/${homelabId}/api-keys/${keyId}`, body),
  revoke: (homelabId: string, keyId: string) =>
    api.delete<void>(`${BASE}/${homelabId}/api-keys/${keyId}`),
  regenerate: (homelabId: string, keyId: string) =>
    api.post<ApiKeyCreated>(`${BASE}/${homelabId}/api-keys/${keyId}/regenerate`),
}
