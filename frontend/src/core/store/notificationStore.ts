import { create } from "zustand"

export interface AppNotification {
  id: string
  level: "success" | "error" | "info"
  title: string
  message: string
  timestamp: number
  dismissed: boolean
}

type NewNotification = Pick<AppNotification, "level" | "title" | "message">

interface NotificationState {
  notifications: AppNotification[]
  addNotification: (n: NewNotification) => void
  dismissToast: (id: string) => void
}

const MAX_NOTIFICATIONS = 20

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],

  addNotification: (n) =>
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
    })),

  dismissToast: (id) =>
    set((state) => ({
      notifications: state.notifications.map((n) =>
        n.id === id ? { ...n, dismissed: true } : n,
      ),
    })),
}))
