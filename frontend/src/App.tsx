import { useEffect } from "react"
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom"
import { useAuthStore } from "./core/store/authStore"
import { useBootstrap } from "./core/hooks/useBootstrap"
import AppLayout from "./app/layouts/AppLayout"
import LoginPage from "./app/pages/LoginPage"
import PersonasPage from "./app/pages/PersonasPage"
import ChatPage from "./app/pages/ChatPage"
import ProjectsPage from "./app/pages/ProjectsPage"
import HistoryPage from "./app/pages/HistoryPage"
import KnowledgePage from "./app/pages/KnowledgePage"
import MemoryPage from "./features/memory/MemoryPage"

/** Persists current /chat/... route to localStorage for bootstrap redirect */
function LastRouteTracker() {
  const location = useLocation()
  useEffect(() => {
    if (location.pathname.startsWith("/chat/")) {
      localStorage.setItem("chatsune_last_route", location.pathname)
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
  if (mustChangePassword) return <Navigate to="/login" replace />

  return <>{children}</>
}

function AppRoutes() {
  useBootstrap()

  return (
    <>
      <LastRouteTracker />
      <Routes>
        <Route path="/login" element={<LoginPage />} />
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
          <Route path="/memory/:personaId" element={<MemoryPage />} />
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
