import { create } from "zustand"
import { safeLocalStorage } from "../utils/safeStorage"

/**
 * Install-prompt handling for Chatsune's PWA.
 *
 * Captures the browser's `beforeinstallprompt` event (Chrome/Edge/Android)
 * so the app can expose an "Install" affordance at a moment of our choosing.
 * iOS Safari does not fire this event — there the user installs via the
 * Share → Add to Home Screen flow and the prompt stays null.
 *
 * The dismissal flag and visit counter are persisted in localStorage so
 * the hint does not reappear after every reload and only shows from the
 * second visit onwards, as per the responsive-design plan.
 */

const DISMISSED_KEY = "chatsune.pwa.install-dismissed"
const VISIT_COUNT_KEY = "chatsune.pwa.visit-count"

// Non-standard event type — not in lib.dom yet.
export interface BeforeInstallPromptEvent extends Event {
  readonly platforms: string[]
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>
}

interface PwaInstallState {
  promptEvent: BeforeInstallPromptEvent | null
  isInstalled: boolean
  dismissed: boolean
  visitCount: number
  setPromptEvent: (e: BeforeInstallPromptEvent | null) => void
  setInstalled: (v: boolean) => void
  dismiss: () => void
  install: () => Promise<"accepted" | "dismissed" | "unavailable">
}

function readDismissed(): boolean {
  return safeLocalStorage.getItem(DISMISSED_KEY) === "1"
}

function readVisitCount(): number {
  const raw = safeLocalStorage.getItem(VISIT_COUNT_KEY)
  const n = raw ? parseInt(raw, 10) : 0
  return Number.isFinite(n) ? n : 0
}

export const usePwaInstallStore = create<PwaInstallState>((set, get) => ({
  promptEvent: null,
  isInstalled:
    typeof window !== "undefined" &&
    window.matchMedia?.("(display-mode: standalone)").matches,
  dismissed: readDismissed(),
  visitCount: readVisitCount(),

  setPromptEvent: (e) => set({ promptEvent: e }),
  setInstalled: (v) => set({ isInstalled: v, promptEvent: null }),

  dismiss: () => {
    safeLocalStorage.setItem(DISMISSED_KEY, "1")
    set({ dismissed: true })
  },

  install: async () => {
    const ev = get().promptEvent
    if (!ev) return "unavailable"
    try {
      await ev.prompt()
      const { outcome } = await ev.userChoice
      if (outcome === "accepted") {
        set({ isInstalled: true, promptEvent: null })
      } else {
        // User declined — remember it so we don't pester.
        safeLocalStorage.setItem(DISMISSED_KEY, "1")
        set({ dismissed: true, promptEvent: null })
      }
      return outcome
    } catch {
      return "unavailable"
    }
  },
}))

/**
 * Bind the global listeners. Call once from the app entry point.
 * Bumps a per-browser visit counter on every boot — the UI uses it to
 * defer the hint until the second visit.
 */
export function initInstallPrompt(): void {
  if (typeof window === "undefined") return

  const nextCount = readVisitCount() + 1
  safeLocalStorage.setItem(VISIT_COUNT_KEY, String(nextCount))
  usePwaInstallStore.setState({ visitCount: nextCount })

  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault()
    usePwaInstallStore
      .getState()
      .setPromptEvent(e as BeforeInstallPromptEvent)
  })

  window.addEventListener("appinstalled", () => {
    usePwaInstallStore.getState().setInstalled(true)
  })
}
