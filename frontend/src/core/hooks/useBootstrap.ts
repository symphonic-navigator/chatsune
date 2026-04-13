import { useEffect, useRef } from "react"
import { authApi } from "../api/auth"
import { meApi } from "../api/meApi"
import { ApiError } from "../api/client"
import { useAuthStore } from "../store/authStore"
import { useEventStore } from "../store/eventStore"
import { useIntegrationsStore } from "../../features/integrations/store"

/** Checks setup status, then attempts a silent token refresh if setup is complete. */
export function useBootstrap() {
  const setToken = useAuthStore((s) => s.setToken)
  const setUser = useAuthStore((s) => s.setUser)
  const setSetupComplete = useAuthStore((s) => s.setSetupComplete)
  const setInitialised = useAuthStore((s) => s.setInitialised)
  const hasRun = useRef(false)

  useEffect(() => {
    if (hasRun.current) return
    hasRun.current = true

    async function bootstrap() {
      try {
        const status = await authApi.status()
        setSetupComplete(status.is_setup_complete)

        if (!status.is_setup_complete) {
          return
        }

        try {
          const response = await authApi.refresh()
          setToken(response.access_token)
          try {
            const me = await meApi.getMe()
            setUser(me)
          } catch {
            // getMe failed — user stays authenticated with fallback display name
          }
          // Fire-and-forget: load integration definitions and user configs
          useIntegrationsStore.getState().load()
        } catch {
          // No valid session — stay logged out
        }
      } catch (err) {
        // Backend unreachable — show unavailable page instead of login
        if (err instanceof ApiError && err.status === 0) {
          useEventStore.getState().setBackendAvailable(false)
          return
        }
        // Other error — assume setup is complete, show login
        setSetupComplete(true)
      } finally {
        setInitialised()
      }
    }

    bootstrap()
  }, [setToken, setUser, setSetupComplete, setInitialised])
}
