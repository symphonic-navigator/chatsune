import { authApi } from "../api/auth"
import { disconnect } from "../websocket/connection"
import { useAuthStore } from "../store/authStore"
import { useNotificationStore } from "../store/notificationStore"

type ForceLogoutReason =
  | "session_expired"
  | "must_change_password"
  | "admin_revoked"

// Holds a navigate function set up by App.tsx during mount. Required
// because forceLogout/logout are called from non-React contexts
// (WebSocket close handlers, API client refresh failures) where
// useNavigate() is not available.
let _navigate: ((path: string) => void) | null = null

export function setNavigate(navigate: (path: string) => void): void {
  _navigate = navigate
}

async function _doLogout(): Promise<void> {
  try {
    await authApi.logout()
  } catch {
    // Best effort; if the server logout call fails we still clean up
    // locally. The user is leaving the session either way.
  }
  disconnect()
  useAuthStore.getState().clear()
  if (_navigate) _navigate("/login")
}

// User pressed the logout button. Quiet, no toast.
export async function logout(): Promise<void> {
  await _doLogout()
}

// System-initiated logout. Always shows a toast on /login so the user
// understands why they were sent here.
export async function forceLogout(
  reason: ForceLogoutReason,
  userMessage: string,
): Promise<void> {
  await _doLogout()
  useNotificationStore.getState().addNotification({
    level: reason === "admin_revoked" ? "warning" : "info",
    title: "Abgemeldet",
    message: userMessage,
  })
}
