import { create } from "zustand"
import type { UserDto } from "../types/auth"
import { configureClient } from "../api/client"

function decodeJwtPayload(token: string): Record<string, unknown> {
  const base64 = token.split(".")[1]
  const json = atob(base64.replace(/-/g, "+").replace(/_/g, "/"))
  return JSON.parse(json)
}

function extractUserFromToken(token: string): UserDto | null {
  try {
    const payload = decodeJwtPayload(token)
    return {
      id: payload.sub as string,
      username: "",
      email: "",
      display_name: "",
      role: payload.role as UserDto["role"],
      is_active: true,
      must_change_password: (payload.mcp as boolean) ?? false,
      created_at: "",
      updated_at: "",
    }
  } catch {
    return null
  }
}

interface AuthState {
  accessToken: string | null
  user: UserDto | null
  isAuthenticated: boolean
  isInitialising: boolean
  isSetupComplete: boolean | null

  setToken: (token: string) => void
  setUser: (user: UserDto) => void
  setSetupComplete: (value: boolean) => void
  setInitialised: () => void
  clear: () => void
}

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  user: null,
  isAuthenticated: false,
  isInitialising: true,
  isSetupComplete: null,

  setSetupComplete: (value: boolean) => set({ isSetupComplete: value }),

  setToken: (token: string) => {
    const partial = extractUserFromToken(token)
    const current = get().user
    const user = current
      ? { ...current, role: partial?.role ?? current.role, must_change_password: partial?.must_change_password ?? false }
      : partial
    set({ accessToken: token, user, isAuthenticated: true })
  },

  setUser: (user: UserDto) => set({ user }),

  setInitialised: () => set({ isInitialising: false }),

  clear: () => set({ accessToken: null, user: null, isAuthenticated: false }),
}))

// Wire up the API client to use the auth store
configureClient({
  getAccessToken: () => useAuthStore.getState().accessToken,
  setAccessToken: (token: string) => useAuthStore.getState().setToken(token),
  onAuthFailure: () => useAuthStore.getState().clear(),
})
