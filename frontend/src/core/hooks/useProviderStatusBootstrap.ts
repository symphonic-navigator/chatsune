import { useEffect } from "react"
import { llmApi } from "../api/llm"
import { eventBus } from "../websocket/eventBus"
import { Topics } from "../types/events"
import { useProviderStatusStore } from "../llm/providerStatusStore"
import { useAuthStore } from "../store/authStore"

/**
 * Fetches the provider-status snapshot once on mount and subscribes
 * to live updates via the WebSocket event bus.
 */
export function useProviderStatusBootstrap() {
  const token = useAuthStore((s) => s.accessToken)
  const setAll = useProviderStatusStore((s) => s.setAll)
  const setStatus = useProviderStatusStore((s) => s.setStatus)

  useEffect(() => {
    if (!token) return

    let cancelled = false

    llmApi
      .getProviderStatuses()
      .then((res) => {
        if (!cancelled) setAll(res.statuses)
      })
      .catch(() => {
        // Endpoint unavailable — pill will fall back to "unknown" states.
      })

    const unsubChanged = eventBus.on(Topics.LLM_PROVIDER_STATUS_CHANGED, (event) => {
      const payload = event.payload as { provider_id?: string; available?: boolean }
      if (typeof payload.provider_id === "string" && typeof payload.available === "boolean") {
        setStatus(payload.provider_id, payload.available)
      }
    })

    const unsubSnapshot = eventBus.on(Topics.LLM_PROVIDER_STATUS_SNAPSHOT, (event) => {
      const payload = event.payload as { statuses?: Record<string, boolean> }
      if (payload.statuses && typeof payload.statuses === "object") {
        setAll(payload.statuses)
      }
    })

    return () => {
      cancelled = true
      unsubChanged()
      unsubSnapshot()
    }
  }, [token, setAll, setStatus])
}
