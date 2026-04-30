import { useEffect } from "react"
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom"
import { useAuthStore } from "./core/store/authStore"
import { useEventStore } from "./core/store/eventStore"
import { useBootstrap } from "./core/hooks/useBootstrap"
import BackendUnavailablePage from "./app/pages/BackendUnavailablePage"
import { registerClientToolHandler } from "./features/code-execution/clientToolHandler"
import { registerSecretsEventHandler } from "./features/integrations/secretsEventHandler"
import { registerIntegrationsEventHandler } from "./features/integrations/integrationsEventHandler"
import { initPluginLifecycle } from "./features/integrations/pluginLifecycle"
import './features/integrations/plugins/lovense'
import './features/integrations/plugins/mistral_voice'
import './features/integrations/plugins/xai_voice'
import './features/integrations/plugins/screen_effects'
import { ScreenEffectsOverlay } from './features/integrations/plugins/screen_effects/overlay/ScreenEffectsOverlay'
import AppLayout from "./app/layouts/AppLayout"
import LoginPage from "./app/pages/LoginPage"
import ChangePasswordPage from "./app/pages/ChangePasswordPage"
import DeletionCompletePage from "./app/pages/DeletionCompletePage"
import RegisterPage from "./app/pages/RegisterPage"
import PersonasPage from "./app/pages/PersonasPage"
import ChatPage from "./app/pages/ChatPage"
import ProjectsPage from "./app/pages/ProjectsPage"
import HistoryPage from "./app/pages/HistoryPage"
import KnowledgePage from "./app/pages/KnowledgePage"
import { safeLocalStorage } from "./core/utils/safeStorage"
import { registerCoreBuiltins, unregisterCoreBuiltins } from "./features/voice-commands"
import { VoiceCommandDebugAlert } from "./app/components/VoiceCommandDebugAlert"


/** Persists current /chat/... route to localStorage for bootstrap redirect */
function LastRouteTracker() {
  const location = useLocation()
  useEffect(() => {
    if (location.pathname.startsWith("/chat/")) {
      safeLocalStorage.setItem("chatsune_last_route", location.pathname)
    }
  }, [location.pathname])
  return null
}

function AuthGuard({ children }: { children: React.ReactNode }) {
  const isInitialising = useAuthStore((s) => s.isInitialising)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const mustChangePassword = useAuthStore((s) => s.user?.must_change_password)

  if (isInitialising) return null
  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (mustChangePassword) return <Navigate to="/change-password" replace />

  return <>{children}</>
}

function LoginRedirect({ children }: { children: React.ReactNode }) {
  const isInitialising = useAuthStore((s) => s.isInitialising)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const mustChangePassword = useAuthStore((s) => s.user?.must_change_password)

  if (isInitialising) return null
  if (isAuthenticated && mustChangePassword)
    return <Navigate to="/change-password" replace />
  if (isAuthenticated) return <Navigate to="/personas" replace />

  return <>{children}</>
}

function ChangePasswordGuard({ children }: { children: React.ReactNode }) {
  const isInitialising = useAuthStore((s) => s.isInitialising)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const mustChangePassword = useAuthStore((s) => s.user?.must_change_password)

  if (isInitialising) return null
  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (!mustChangePassword) return <Navigate to="/personas" replace />

  return <>{children}</>
}

function AppRoutes() {
  useBootstrap()
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const backendAvailable = useEventStore((s) => s.backendAvailable)

  useEffect(() => {
    if (!isAuthenticated) return

    registerCoreBuiltins()
    const unregisterClientTool = registerClientToolHandler()
    const unregisterSecrets = registerSecretsEventHandler()
    const unregisterIntegrations = registerIntegrationsEventHandler()
    const cleanupPluginLifecycle = initPluginLifecycle()
    return () => {
      unregisterClientTool()
      unregisterSecrets()
      unregisterIntegrations()
      cleanupPluginLifecycle()
      unregisterCoreBuiltins()
    }
  }, [isAuthenticated])

  if (!backendAvailable) return <BackendUnavailablePage />

  return (
    <>
      <LastRouteTracker />
      <Routes>
        <Route
          path="/login"
          element={
            <LoginRedirect>
              <LoginPage />
            </LoginRedirect>
          }
        />
        <Route
          path="/change-password"
          element={
            <ChangePasswordGuard>
              <ChangePasswordPage />
            </ChangePasswordGuard>
          }
        />
        {/* Public — user is logged out by the time they land here (self-delete).
            Must render unconditionally, outside AuthGuard, with no LoginRedirect. */}
        <Route
          path="/deletion-complete/:slug"
          element={<DeletionCompletePage />}
        />
        <Route path="/register/:token" element={<RegisterPage />} />
        <Route
          element={
            <AuthGuard>
              <AppLayout />
            </AuthGuard>
          }
        >
          <Route path="/personas" element={<PersonasPage />} />
          <Route path="/chat/:personaId/:sessionId?" element={<ChatPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />

          <Route path="/admin/*" element={<Navigate to="/personas" replace />} />
        </Route>
        <Route path="*" element={<Navigate to="/personas" replace />} />
      </Routes>
      <ScreenEffectsOverlay />
      <VoiceCommandDebugAlert />
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}
