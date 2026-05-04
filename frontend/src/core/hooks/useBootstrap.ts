import { useEffect, useRef } from "react"
import { authApi } from "../api/auth"
import { meApi } from "../api/meApi"
import { ApiError } from "../api/client"
import { useAuthStore } from "../store/authStore"
import { useEventStore } from "../store/eventStore"
import { useIntegrationsStore } from "../../features/integrations/store"
import { useProjectsStore } from "../../features/projects/useProjectsStore"

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
          // Mindspace: hydrate the projects store as soon as the user is
          // authenticated. The sidebar Projects-zone (Phase 6) and the
          // ProjectsTab in UserModal both read from this store; firing
          // the load here means the data is already in memory by the
          // time those surfaces render.
          void useProjectsStore.getState().load()
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
