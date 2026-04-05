type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE"

let getAccessToken: () => string | null = () => null
let setAccessToken: (token: string) => void = () => {}
let onAuthFailure: () => void = () => {}

export function configureClient(config: {
  getAccessToken: () => string | null
  setAccessToken: (token: string) => void
  onAuthFailure: () => void
}) {
  getAccessToken = config.getAccessToken
  setAccessToken = config.setAccessToken
  onAuthFailure = config.onAuthFailure
}

function baseUrl(): string {
  return import.meta.env.VITE_API_URL ?? ""
}

async function refreshToken(): Promise<boolean> {
  try {
    const res = await fetch(`${baseUrl()}/api/auth/refresh`, {
      method: "POST",
      credentials: "include",
    })
    if (!res.ok) return false
    const data = await res.json()
    setAccessToken(data.access_token)
    return true
  } catch {
    return false
  }
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

  let res = await fetch(`${baseUrl()}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "include",
  })

  if (res.status === 401 && !skipAuth) {
    const refreshed = await refreshToken()
    if (refreshed) {
      const token = getAccessToken()
      if (token) {
        headers["Authorization"] = `Bearer ${token}`
      }
      res = await fetch(`${baseUrl()}${path}`, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        credentials: "include",
      })
    } else {
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
