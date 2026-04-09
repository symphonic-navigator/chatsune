import { create } from "zustand"
import { hapticError } from "../utils/haptics"

export interface NotificationAction {
  label: string
  onClick: () => void
}

export interface AppNotification {
  id: string
  level: "success" | "error" | "info" | "warning"
  title: string
  message: string
  action?: NotificationAction
  duration?: number
  timestamp: number
  dismissed: boolean
}

type NewNotification = Pick<AppNotification, "level" | "title" | "message"> &
  Partial<Pick<AppNotification, "action" | "duration">>

interface NotificationState {
  notifications: AppNotification[]
  addNotification: (n: NewNotification) => void
  dismissToast: (id: string) => void
}

const MAX_NOTIFICATIONS = 20

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],

  addNotification: (n) => {
    // Buzz on error-level notifications so the user feels something went
    // wrong even if they are not looking at the toast region.
    if (n.level === "error") hapticError()
    set((state) => ({
      notifications: [
        {
          ...n,
          id: crypto.randomUUID(),
          timestamp: Date.now(),
          dismissed: false,
        },
        ...state.notifications,
      ].slice(0, MAX_NOTIFICATIONS),
    }))
  },

  dismissToast: (id) =>
    set((state) => ({
      notifications: state.notifications.map((n) =>
        n.id === id ? { ...n, dismissed: true } : n,
      ),
    })),
}))
