import { useCallback, useState } from "react"
import { useAuthStore } from "../store/authStore"
import { authApi } from "../api/auth"
import type { LoginResult, SetupResult } from "../api/auth"
import { meApi } from "../api/meApi"
import { disconnect } from "../websocket/connection"
import { logout as coordinatorLogout } from "../auth/logoutCoordinator"
import { useIntegrationsStore } from "../../features/integrations/store"
import type { LoginRequest, SetupRequest } from "../types/auth"

export type { LoginResult, SetupResult }

function loadAuthenticatedIntegrationState(): void {
  void useIntegrationsStore.getState().load()
}

export function useAuth() {
  const { user, isAuthenticated, accessToken, setToken, setUser, clear } =
    useAuthStore()
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const login = useCallback(async (data: LoginRequest): Promise<LoginResult> => {
    setIsLoading(true)
    setError(null)
    try {
      const result = await authApi.login(data.username, data.password)
      // For 'ok' we finalise auth immediately. For 'legacy_upgrade' we must
      // NOT call setToken here — it would flip isAuthenticated to true and
      // App.tsx's <PublicRoute> would redirect to /personas before the
      // caller gets a chance to show the one-shot recovery-key modal. The
      // caller is responsible for calling finaliseLogin(accessToken) after
      // the user acknowledges the modal.
      if (result.kind === 'ok') {
        setToken(result.accessToken!)
        try {
          const me = await meApi.getMe()
          setUser(me)
        } catch {
          // getMe failed — user stays authenticated with fallback display name
        }
        loadAuthenticatedIntegrationState()
      }
      return result
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed")
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [setToken, setUser])

  const finaliseLogin = useCallback(async (accessToken: string): Promise<void> => {
    setToken(accessToken)
    try {
      const me = await meApi.getMe()
      setUser(me)
    } catch {
      // getMe failed — user stays authenticated with fallback display name
    }
    loadAuthenticatedIntegrationState()
  }, [setToken, setUser])

  const setup = useCallback(async (data: SetupRequest): Promise<SetupResult> => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await authApi.setup({
        username: data.username,
        email: data.email,
        displayName: data.display_name ?? data.username,
        pin: data.pin,
        password: data.password,
      })
      setToken(res.accessToken)
      setUser(res.user)
      loadAuthenticatedIntegrationState()
      return res
    } catch (err) {
      setError(err instanceof Error ? err.message : "Setup failed")
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [setToken, setUser])

  const changePassword = useCallback(async (data: { username: string; current_password: string; new_password: string }): Promise<void> => {
    setIsLoading(true)
    setError(null)
    try {
      await authApi.changePassword(data.username, data.current_password, data.new_password)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Password change failed")
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [])

  const logout = useCallback(async () => {
    await coordinatorLogout()
  }, [])

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
    finaliseLogin,
    setup,
    changePassword,
    logout,
    deleteAccount,
  }
}
