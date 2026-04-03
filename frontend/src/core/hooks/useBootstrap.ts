import { useEffect } from "react"
import { authApi } from "../api/auth"
import { useAuthStore } from "../store/authStore"

/** Attempts a silent token refresh on mount to restore an existing session. */
export function useBootstrap() {
  const setToken = useAuthStore((s) => s.setToken)
  const setInitialised = useAuthStore((s) => s.setInitialised)

  useEffect(() => {
    authApi
      .refresh()
      .then((response) => {
        setToken(response.access_token)
      })
      .catch(() => {
        // No valid session — stay logged out
      })
      .finally(() => {
        setInitialised()
      })
    // Run once on mount only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}
