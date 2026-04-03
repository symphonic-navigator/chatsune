import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { useAuthStore } from "./core/store/authStore"
import { useWebSocket } from "./core/hooks/useWebSocket"
import PrototypeLayout from "./prototype/layouts/PrototypeLayout"

import LoginPage from "./prototype/pages/LoginPage"
import DashboardPage from "./prototype/pages/DashboardPage"
import UsersPage from "./prototype/pages/UsersPage"
import LlmPage from "./prototype/pages/LlmPage"
import PersonasPage from "./prototype/pages/PersonasPage"
import AdminPage from "./prototype/pages/AdminPage"

function AuthGuard({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const mustChangePassword = useAuthStore((s) => s.user?.must_change_password)

  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (mustChangePassword) return <Navigate to="/login" replace />

  return <>{children}</>
}

function AppRoutes() {
  useWebSocket()

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <AuthGuard>
            <PrototypeLayout />
          </AuthGuard>
        }
      >
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/users" element={<UsersPage />} />
        <Route path="/llm" element={<LlmPage />} />
        <Route path="/personas" element={<PersonasPage />} />
        <Route path="/admin" element={<AdminPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}
