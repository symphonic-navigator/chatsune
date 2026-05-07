import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface BargeSettingsState {
  enabled: boolean
  setEnabled: (next: boolean) => void
  toggle: () => void
}

/**
 * Per-device user preference for whether the user can interrupt the
 * persona's TTS playback by speaking ("barging on"), or whether the
 * mic is held back while the persona speaks ("barging off").
 *
 * Default true matches today's behaviour exactly. The state is purely
 * a user preference and is not reset on session/live-mode exit.
 *
 * See devdocs/specs/2026-05-07-barging-toggle-design.md.
 */
export const useBargeSettingsStore = create<BargeSettingsState>()(
  persist(
    (set) => ({
      enabled: true,
      setEnabled: (next) => set({ enabled: next }),
      toggle: () => set((s) => ({ enabled: !s.enabled })),
    }),
    { name: 'voice.barging.enabled' },
  ),
)
