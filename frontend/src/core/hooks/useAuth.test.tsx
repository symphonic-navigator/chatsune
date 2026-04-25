import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuth } from './useAuth'
import { authApi } from '../api/auth'
import { meApi } from '../api/meApi'
import { useAuthStore } from '../store/authStore'
import { useIntegrationsStore } from '../../features/integrations/store'
import type { UserDto } from '../types/auth'

vi.mock('../api/auth', () => ({
  authApi: {
    login: vi.fn(),
    setup: vi.fn(),
    changePassword: vi.fn(),
    logout: vi.fn(),
    deleteAccount: vi.fn(),
  },
}))

vi.mock('../api/meApi', () => ({
  meApi: {
    getMe: vi.fn(),
  },
}))

vi.mock('../websocket/connection', () => ({
  disconnect: vi.fn(),
}))

vi.mock('../../features/integrations/store', () => ({
  useIntegrationsStore: {
    getState: vi.fn(),
  },
}))

const user: UserDto = {
  id: 'user-1',
  username: 'neo',
  email: 'neo@zion.invalid',
  display_name: 'Neo',
  role: 'user',
  is_active: true,
  must_change_password: false,
  created_at: '',
  updated_at: '',
  recent_emojis: [],
}

function tokenFor(payload: Record<string, unknown> = { sub: user.id, role: user.role, mcp: false }): string {
  return `e30.${btoa(JSON.stringify(payload))}.sig`
}

describe('useAuth', () => {
  const loadIntegrations = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({
      accessToken: null,
      user: null,
      isAuthenticated: false,
      isInitialising: false,
      isSetupComplete: true,
    })
    loadIntegrations.mockResolvedValue(undefined)
    vi.mocked(useIntegrationsStore.getState).mockReturnValue({
      load: loadIntegrations,
    } as unknown as ReturnType<typeof useIntegrationsStore.getState>)
  })

  it('loads integrations after explicit login so voice plugins can activate', async () => {
    vi.mocked(authApi.login).mockResolvedValueOnce({
      kind: 'ok',
      accessToken: tokenFor(),
      expiresIn: 900,
    })
    vi.mocked(meApi.getMe).mockResolvedValueOnce(user)

    const { result } = renderHook(() => useAuth())

    await act(async () => {
      await result.current.login({ username: 'neo', password: 'trinity' })
    })

    expect(useAuthStore.getState().isAuthenticated).toBe(true)
    expect(loadIntegrations).toHaveBeenCalledTimes(1)
  })

  it('loads integrations after initial setup login', async () => {
    vi.mocked(authApi.setup).mockResolvedValueOnce({
      accessToken: tokenFor(),
      expiresIn: 900,
      recoveryKey: 'XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX',
      user,
    })

    const { result } = renderHook(() => useAuth())

    await act(async () => {
      await result.current.setup({
        pin: '1234',
        username: user.username,
        email: user.email,
        password: 'there-is-no-spoon',
      })
    })

    expect(useAuthStore.getState().isAuthenticated).toBe(true)
    expect(loadIntegrations).toHaveBeenCalledTimes(1)
  })
})
