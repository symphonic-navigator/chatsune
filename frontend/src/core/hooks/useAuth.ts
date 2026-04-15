import { useCallback, useState } from "react"
import { useAuthStore } from "../store/authStore"
import { authApi } from "../api/auth"
import { meApi } from "../api/meApi"
import { disconnect } from "../websocket/connection"
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

  /**
   * Self-delete the currently-signed-in account (right-to-be-forgotten).
   *
   * The DELETE handler revokes every session server-side and clears the
   * refresh cookie — we must NOT also call /api/auth/logout afterwards,
   * because that would require a valid access token we no longer have.
   *
   * On success the WebSocket is disconnected and the auth store is cleared
   * so the caller can navigate to the public `/deletion-complete/:slug`
   * page without the AuthGuard bouncing it back to /login.
   *
   * Errors are surfaced via the hook's `error` state AND re-thrown so the
   * caller can `try/catch` and branch on the ApiError status code (400 =
   * username mismatch, 403 = master admin cannot self-delete).
   */
  const deleteAccount = useCallback(
    async (confirmUsername: string) => {
      setIsLoading(true)
      setError(null)
      try {
        const res = await authApi.deleteAccount(confirmUsername)
        disconnect()
        clear()
        return res
      } catch (err) {
        setError(err instanceof Error ? err.message : "Account deletion failed")
        throw err
      } finally {
        setIsLoading(false)
      }
    },
    [clear],
  )

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
    deleteAccount,
  }
}
