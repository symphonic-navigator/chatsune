import { api, apiRequest } from "./client"
import type {
  LoginRequest,
  SetupRequest,
  SetupResponse,
  TokenResponse,
  ChangePasswordRequest,
} from "../types/auth"
import type { DeletionReportDto } from "../types/deletion"

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

  // Right-to-be-forgotten: authenticated user deletes their own account.
  // The server-side handler revokes every session and clears the refresh
  // cookie — the caller should NOT also call /api/auth/logout afterwards.
  // Returns a short-lived (15-min Redis TTL) `slug` keyed to the report.
  deleteAccount: (confirmUsername: string) =>
    apiRequest<{ slug: string; success: boolean }>(
      "DELETE",
      "/api/users/me",
      { confirm_username: confirmUsername },
    ),

  // Public lookup of the deletion report by slug. No auth — the user is
  // logged out by the time they land on /deletion-complete/:slug.
  getDeletionReport: (slug: string) =>
    apiRequest<DeletionReportDto>(
      "GET",
      `/api/auth/deletion-report/${encodeURIComponent(slug)}`,
      undefined,
      true,
    ),
}
