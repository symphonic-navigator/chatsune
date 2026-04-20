import { usePwaInstallStore } from "../pwa/installPrompt"

/**
 * Returns `true` if the app is currently running as an installed PWA
 * (display-mode: standalone). Wraps the already-maintained `isInstalled`
 * flag in `usePwaInstallStore`, which is initialised from
 * `matchMedia('(display-mode: standalone)')` and updated on the
 * `appinstalled` window event.
 *
 * Callers should use this hook rather than duplicating the matchMedia
 * check so the single source of truth stays in the store.
 */
export function useIsPwa(): boolean {
  return usePwaInstallStore((s) => s.isInstalled)
}
