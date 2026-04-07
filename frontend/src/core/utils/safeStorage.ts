/**
 * Safe wrapper around `localStorage` that swallows access errors.
 *
 * `localStorage` can throw in several real-world scenarios:
 *   - Private / incognito modes with storage disabled
 *   - Storage quota exceeded
 *   - Cross-origin iframe sandboxing
 *   - User-disabled cookies/storage in browser settings
 *
 * Rather than crash the UI, callers get a sensible fallback value.
 */
export const safeLocalStorage = {
  getItem(key: string): string | null {
    try {
      return localStorage.getItem(key)
    } catch {
      return null
    }
  },
  setItem(key: string, value: string): void {
    try {
      localStorage.setItem(key, value)
    } catch {
      // Ignore — best-effort persistence only.
    }
  },
  removeItem(key: string): void {
    try {
      localStorage.removeItem(key)
    } catch {
      // Ignore.
    }
  },
  hasItem(key: string): boolean {
    try {
      return localStorage.getItem(key) !== null
    } catch {
      return false
    }
  },
}
