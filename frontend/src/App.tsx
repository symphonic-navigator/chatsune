import { useEffect } from "react"
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom"
import { useAuthStore } from "./core/store/authStore"
import { useBootstrap } from "./core/hooks/useBootstrap"
import { registerClientToolHandler } from "./features/code-execution/clientToolHandler"
import AppLayout from "./app/layouts/AppLayout"
import LoginPage from "./app/pages/LoginPage"
import ChangePasswordPage from "./app/pages/ChangePasswordPage"
import PersonasPage from "./app/pages/PersonasPage"
import ChatPage from "./app/pages/ChatPage"
import ProjectsPage from "./app/pages/ProjectsPage"
import HistoryPage from "./app/pages/HistoryPage"
import KnowledgePage from "./app/pages/KnowledgePage"
import { safeLocalStorage } from "./core/utils/safeStorage"


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

  useEffect(() => {
    if (!isAuthenticated) return

    const unregisterClientTool = registerClientToolHandler()
    return () => {
      unregisterClientTool()
    }
  }, [isAuthenticated])

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
