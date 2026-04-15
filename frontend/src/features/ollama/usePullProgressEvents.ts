import { useEffect } from "react"
import { eventBus } from "../../core/websocket/eventBus"
import { usePullProgressStore } from "../../core/store/pullProgressStore"
import { useNotificationStore } from "../../core/store/notificationStore"
import type { BaseEvent } from "../../core/types/events"

interface PullFailedPayload {
  slug?: string
  user_message?: string
}

/**
 * Subscribes the pull-progress store to the 'llm.model.pull.*' event stream
 * and raises an error toast when a pull fails. Mount exactly once at the
 * top of the authenticated tree (e.g. AppLayout).
 */
export function usePullProgressEvents() {
  useEffect(() => {
    const handler = usePullProgressStore.getState().handleEvent
    const unsubAll = eventBus.on("llm.model.pull.*", handler)

    const unsubFailed = eventBus.on(
      "llm.model.pull.failed",
      (event: BaseEvent) => {
        const p = event.payload as unknown as PullFailedPayload
        useNotificationStore.getState().addNotification({
          level: "error",
          title: `Pull failed: ${p.slug ?? "unknown"}`,
          message: p.user_message ?? "Unknown error",
        })
      },
    )

    return () => {
      unsubAll()
      unsubFailed()
    }
  }, [])
}
