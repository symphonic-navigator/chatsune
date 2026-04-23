import { apiRequest, api } from "./client"
import { deriveAuthAndKek, toBase64Url, fromBase64Url } from "../crypto/keyDerivation"
import type { KdfParams } from "../crypto/keyDerivation"
import { generateRecoveryKey } from "../crypto/recoveryKey"
import type { DeletionReportDto } from "../types/deletion"
import type { UserDto } from "../types/auth"

export interface KdfParamsResponse {
  kdf_salt: string       // urlsafe-base64
  kdf_params: KdfParams
  password_hash_version: number | null
}

export interface LoginResult {
  kind: 'ok' | 'recovery_required' | 'legacy_upgrade'
  accessToken?: string
  expiresIn?: number
  recoveryKey?: string   // only for legacy_upgrade
}

export interface SetupResult {
  accessToken: string
  expiresIn: number
  recoveryKey: string    // client-generated; returned so the modal can display it
  user: UserDto
}


async function fetchKdfParams(username: string): Promise<KdfParamsResponse> {
  return apiRequest<KdfParamsResponse>("POST", "/api/auth/kdf-params", { username }, true)
}

async function deriveFromPassword(
  password: string,
  params: KdfParamsResponse,
): Promise<{ hAuth: string; hKek: string }> {
  const salt = fromBase64Url(params.kdf_salt)
  const { hAuth, hKek } = await deriveAuthAndKek(password, salt, params.kdf_params)
  return { hAuth: toBase64Url(hAuth), hKek: toBase64Url(hKek) }
}


export const authApi = {
  async login(username: string, password: string): Promise<LoginResult> {
    const params = await fetchKdfParams(username)
    const { hAuth, hKek } = await deriveFromPassword(password, params)

    if (params.password_hash_version === null) {
      // Legacy user — drive the one-time migration path
      const resp = await apiRequest<{ access_token: string; expires_in: number; recovery_key: string }>(
        "POST", "/api/auth/login-legacy", { username, password, h_auth: hAuth, h_kek: hKek }, true,
      )
      return { kind: 'legacy_upgrade', accessToken: resp.access_token, expiresIn: resp.expires_in, recoveryKey: resp.recovery_key }
    }

    const resp = await apiRequest<{ access_token?: string; expires_in?: number; status?: string }>(
      "POST", "/api/auth/login", { username, h_auth: hAuth, h_kek: hKek }, true,
    )
    if (resp.status === 'recovery_required') return { kind: 'recovery_required' }
    return { kind: 'ok', accessToken: resp.access_token!, expiresIn: resp.expires_in! }
  },

  async recoverDek(username: string, newPassword: string, recoveryKey: string): Promise<{ accessToken: string; expiresIn: number }> {
    const params = await fetchKdfParams(username)
    const { hAuth, hKek } = await deriveFromPassword(newPassword, params)
    const resp = await apiRequest<{ access_token: string; expires_in: number }>(
      "POST", "/api/auth/recover-dek", { username, h_auth: hAuth, h_kek: hKek, recovery_key: recoveryKey }, true,
    )
    return { accessToken: resp.access_token, expiresIn: resp.expires_in }
  },

  async declineRecovery(username: string): Promise<void> {
    await apiRequest<void>("POST", "/api/auth/decline-recovery", { username }, true)
  },

  async changePassword(username: string, oldPassword: string, newPassword: string): Promise<void> {
    const params = await fetchKdfParams(username)
    const oldKeys = await deriveFromPassword(oldPassword, params)
    const newKeys = await deriveFromPassword(newPassword, params)
    await apiRequest<void>("POST", "/api/auth/change-password", {
      h_auth_old: oldKeys.hAuth,
      h_kek_old: oldKeys.hKek,
      h_auth_new: newKeys.hAuth,
      h_kek_new: newKeys.hKek,
    })
  },

  async setup(opts: { username: string; email: string; displayName: string; pin: string; password: string }): Promise<SetupResult> {
    const params = await fetchKdfParams(opts.username)
    const salt = fromBase64Url(params.kdf_salt)
    const { hAuth, hKek } = await deriveAuthAndKek(opts.password, salt, params.kdf_params)
    const recoveryKey = generateRecoveryKey()
    const resp = await apiRequest<{ access_token: string; expires_in: number; user: UserDto }>(
      "POST", "/api/auth/setup", {
        username: opts.username,
        email: opts.email,
        display_name: opts.displayName,
        pin: opts.pin,
        h_auth: toBase64Url(hAuth),
        h_kek: toBase64Url(hKek),
        recovery_key: recoveryKey,
      }, true,
    )
    return { accessToken: resp.access_token, expiresIn: resp.expires_in, recoveryKey, user: resp.user }
  },

  refresh: () =>
    apiRequest<{ access_token: string; token_type: string; expires_in: number }>("POST", "/api/auth/refresh", undefined, true),

  logout: () => api.post<{ status: string }>("/api/auth/logout"),

  status: () =>
    apiRequest<{ is_setup_complete: boolean }>("GET", "/api/auth/status", undefined, true),

  // Right-to-be-forgotten: authenticated user deletes their own account.
  // The server-side handler revokes every session and clears the refresh
  // cookie — the caller must NOT also call /api/auth/logout afterwards.
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
