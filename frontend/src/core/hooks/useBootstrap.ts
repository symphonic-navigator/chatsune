import { useEffect, useRef } from "react"
import { authApi } from "../api/auth"
import { meApi } from "../api/meApi"
import { useAuthStore } from "../store/authStore"

/** Attempts a silent token refresh on mount to restore an existing session. */
export function useBootstrap() {
  const setToken = useAuthStore((s) => s.setToken)
  const setUser = useAuthStore((s) => s.setUser)
  const setInitialised = useAuthStore((s) => s.setInitialised)
  const hasRun = useRef(false)

  useEffect(() => {
    if (hasRun.current) return
    hasRun.current = true

    authApi
      .refresh()
      .then(async (response) => {
        setToken(response.access_token)
        try {
          const me = await meApi.getMe()
          setUser(me)
        } catch {
          // getMe failed — user stays authenticated with fallback display name
        }
      })
      .catch(() => {
        // No valid session — stay logged out
      })
      .finally(() => {
        setInitialised()
      })
  }, [])
}
