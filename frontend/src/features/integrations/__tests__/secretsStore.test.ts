import { describe, expect, it, beforeEach } from 'vitest'
import { useSecretsStore } from '../secretsStore'

describe('secretsStore', () => {
  beforeEach(() => {
    useSecretsStore.setState({ secrets: {} })
    localStorage.clear()
  })

  it('stores and retrieves a secret', () => {
    useSecretsStore.getState().setSecrets('mistral_voice', { api_key: 'sk-abc' })
    expect(useSecretsStore.getState().getSecret('mistral_voice', 'api_key')).toBe('sk-abc')
  })

  it('reports hasSecrets correctly', () => {
    expect(useSecretsStore.getState().hasSecrets('mistral_voice')).toBe(false)
    useSecretsStore.getState().setSecrets('mistral_voice', { api_key: 'sk-abc' })
    expect(useSecretsStore.getState().hasSecrets('mistral_voice')).toBe(true)
  })

  it('clearSecrets removes the integration entry', () => {
    useSecretsStore.getState().setSecrets('mistral_voice', { api_key: 'sk-abc' })
    useSecretsStore.getState().clearSecrets('mistral_voice')
    expect(useSecretsStore.getState().getSecret('mistral_voice', 'api_key')).toBeUndefined()
  })

  it('does NOT use persist middleware (localStorage stays empty)', () => {
    useSecretsStore.getState().setSecrets('mistral_voice', { api_key: 'sk-abc' })
    expect(localStorage?.length ?? 0).toBe(0)
  })
})
