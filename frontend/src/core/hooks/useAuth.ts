import { useCallback, useState } from "react"
import { useAuthStore } from "../store/authStore"
import { authApi } from "../api/auth"
import { meApi } from "../api/meApi"
import { connect, disconnect } from "../websocket/connection"
import type {
  LoginRequest,
  SetupRequest,
  ChangePasswordRequest,
} from "../types/auth"

export function useAuth() {
  const { user, isAuthenticated, accessToken, setToken, setUser, clear } =
    useAuthStore()
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const login = useCallback(async (data: LoginRequest) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await authApi.login(data)
      setToken(res.access_token)
      try {
        const me = await meApi.getMe()
        setUser(me)
      } catch {
        // getMe failed — user stays authenticated with fallback display name
      }
      connect()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed")
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [setToken, setUser])

  const setup = useCallback(async (data: SetupRequest) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await authApi.setup(data)
      setToken(res.access_token)
      setUser(res.user)
      connect()
      return res
    } catch (err) {
      setError(err instanceof Error ? err.message : "Setup failed")
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [setToken, setUser])

  const changePassword = useCallback(async (data: ChangePasswordRequest) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await authApi.changePassword(data)
      setToken(res.access_token)
      disconnect()
      connect()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Password change failed")
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [setToken])

  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch {
      // Logout should succeed even if the API call fails
    } finally {
      disconnect()
      clear()
    }
  }, [clear])

  return {
    user,
    isAuthenticated,
    accessToken,
    isLoading,
    error,
    login,
    setup,
    changePassword,
    logout,
  }
}
