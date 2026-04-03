import { api, apiRequest } from "./client"
import type {
  LoginRequest,
  SetupRequest,
  SetupResponse,
  TokenResponse,
  ChangePasswordRequest,
} from "../types/auth"

export const authApi = {
  login: (data: LoginRequest) =>
    apiRequest<TokenResponse>("POST", "/api/auth/login", data, true),

  refresh: () =>
    apiRequest<TokenResponse>("POST", "/api/auth/refresh", undefined, true),

  logout: () => api.post<{ status: string }>("/api/auth/logout"),

  changePassword: (data: ChangePasswordRequest) =>
    api.patch<TokenResponse>("/api/auth/password", data),

  setup: (data: SetupRequest) =>
    apiRequest<SetupResponse>("POST", "/api/setup", data, true),

  status: () =>
    apiRequest<{ is_setup_complete: boolean }>("GET", "/api/auth/status", undefined, true),
}
