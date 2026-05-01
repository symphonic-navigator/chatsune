type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE"

const BACKEND_MARKER_HEADER = "X-Chatsune-Backend"

export class BackendUnavailableError extends Error {
  constructor(reason: string) {
    super(`Backend unavailable: ${reason}`)
    this.name = "BackendUnavailableError"
  }
}

let getAccessToken: () => string | null = () => null
let setAccessToken: (token: string) => void = () => {}
let onAuthFailure: () => void = () => {}
let onBackendUnavailable: () => void = () => {}

export function configureClient(config: {
  getAccessToken: () => string | null
  setAccessToken: (token: string) => void
  onAuthFailure: () => void
  onBackendUnavailable?: () => void
}) {
  getAccessToken = config.getAccessToken
  setAccessToken = config.setAccessToken
  onAuthFailure = config.onAuthFailure
  onBackendUnavailable = config.onBackendUnavailable ?? (() => {})
}

function baseUrl(): string {
  return import.meta.env.VITE_API_URL ?? ""
}

// Prepend the configured API base URL to a relative path. Centralises the
// VITE_API_URL prefix so that every fetch-based API client — including the
// integration plugins that live outside this module — routes through the
// same origin. Without this, relative URLs hit the frontend origin, which
// in split-origin Docker setups (frontend :5080, backend :5079) produces
// 405 Not Allowed and silent voice-list failures.
export function apiUrl(path: string): string {
  return `${baseUrl()}${path}`
}

function isNetworkError(err: unknown): boolean {
  return err instanceof TypeError && (err.message === "Failed to fetch" || err.message === "Load failed")
}

export type RefreshOutcome = "ok" | "auth_failed" | "backend_unavailable"

let currentRefresh: Promise<RefreshOutcome> | null = null

export async function refreshToken(): Promise<RefreshOutcome> {
  // Share the in-flight refresh promise so parallel 401s coalesce into a
  // single refresh call.
  if (currentRefresh) return currentRefresh
  currentRefresh = (async () => {
    try {
      const res = await fetch(apiUrl("/api/auth/refresh"), {
        method: "POST",
        credentials: "include",
      })
      // No marker header → response did not come from our backend
      // (proxy fall-through). This is NOT an auth failure; do not log
      // the user out. The health monitor will pick up the backend-down
      // state.
      if (!res.headers.has(BACKEND_MARKER_HEADER)) {
        return "backend_unavailable"
      }
      if (!res.ok) return "auth_failed"
      const data = await res.json()
      setAccessToken(data.access_token)
      return "ok"
    } catch (err) {
      return isNetworkError(err) ? "backend_unavailable" : "auth_failed"
    } finally {
      currentRefresh = null
    }
  })()
  return currentRefresh
}

export async function apiRequest<T>(
  method: HttpMethod,
  path: string,
  body?: unknown,
  skipAuth = false,
): Promise<T> {
  const headers: Record<string, string> = {}

  if (body !== undefined) {
    headers["Content-Type"] = "application/json"
  }

  if (!skipAuth) {
    const token = getAccessToken()
    if (token) {
      headers["Authorization"] = `Bearer ${token}`
    }
  }

  let res: Response
  try {
    res = await fetch(apiUrl(path), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: "include",
    })
  } catch (err) {
    if (isNetworkError(err)) {
      onBackendUnavailable()
      throw new BackendUnavailableError("network error")
    }
    throw err
  }

  // If the response did not come from our backend (proxy fall-through,
  // frontend nginx, browser cache, etc.), the marker header is absent.
  // Treat this as "backend unreachable", not as an authoritative result.
  if (!res.headers.has(BACKEND_MARKER_HEADER)) {
    onBackendUnavailable()
    throw new BackendUnavailableError(`no marker header (status ${res.status})`)
  }

  if (res.status === 401 && !skipAuth) {
    const refreshed = await refreshToken()
    if (refreshed === "ok") {
      const token = getAccessToken()
      if (token) {
        headers["Authorization"] = `Bearer ${token}`
      }
      res = await fetch(apiUrl(path), {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        credentials: "include",
      })
      if (!res.headers.has(BACKEND_MARKER_HEADER)) {
        onBackendUnavailable()
        throw new BackendUnavailableError("retry response missing marker")
      }
    } else if (refreshed === "backend_unavailable") {
      onBackendUnavailable()
      throw new BackendUnavailableError("refresh failed: backend unavailable")
    } else {
      // refreshed === "auth_failed": the backend authoritatively rejected
      // the refresh. The user's session is over.
      onAuthFailure()
      throw new ApiError(401, "Authentication failed")
    }
  }

  if (!res.ok) {
    const errorBody = await res.json().catch(() => null)
    throw new ApiError(res.status, errorBody?.detail ?? res.statusText, errorBody)
  }

  if (res.status === 204) return undefined as T

  return res.json() as Promise<T>
}

export class ApiError extends Error {
  status: number
  body?: unknown

  constructor(status: number, message: string, body?: unknown) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.body = body
  }
}

export const api = {
  get: <T>(path: string) => apiRequest<T>("GET", path),
  post: <T>(path: string, body?: unknown) => apiRequest<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => apiRequest<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => apiRequest<T>("PATCH", path, body),
  delete: <T>(path: string) => apiRequest<T>("DELETE", path),
  postNoAuth: <T>(path: string, body?: unknown) => apiRequest<T>("POST", path, body, true),
}

export function currentAccessToken(): string | null {
  return getAccessToken()
}
