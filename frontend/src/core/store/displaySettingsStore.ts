import { create } from 'zustand'
import {
  type DisplaySettings,
  DEFAULT_DISPLAY_SETTINGS,
  FONT_FAMILY_VALUES,
  FONT_SIZE_VALUES,
  LINE_HEIGHT_VALUES,
} from '../types/displaySettings'

const STORAGE_KEY = 'chatsune_display_settings'

export function loadDisplaySettings(): DisplaySettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { ...DEFAULT_DISPLAY_SETTINGS }
    return { ...DEFAULT_DISPLAY_SETTINGS, ...JSON.parse(raw) }
  } catch {
    return { ...DEFAULT_DISPLAY_SETTINGS }
  }
}

export function saveDisplaySettings(settings: DisplaySettings): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  applyCssVars(settings)
}

const WHITE_SCRIPT_COLOUR = '#f7f3eb'

function applyCssVars(settings: DisplaySettings): void {
  const root = document.documentElement
  root.style.setProperty('--chat-font-family', FONT_FAMILY_VALUES[settings.chatFontFamily])
  root.style.setProperty('--chat-font-size', FONT_SIZE_VALUES[settings.chatFontSize])
  root.style.setProperty('--chat-line-height', LINE_HEIGHT_VALUES[settings.chatLineHeight])
  root.style.setProperty('--ui-scale', String(settings.uiScale / 100))

  if (settings.whiteScript) {
    root.classList.add('white-script')
    root.style.setProperty('--chat-text-colour', WHITE_SCRIPT_COLOUR)
  } else {
    root.classList.remove('white-script')
    root.style.removeProperty('--chat-text-colour')
  }
}

interface DisplaySettingsState {
  settings: DisplaySettings
  update: (patch: Partial<DisplaySettings>) => void
}

export const useDisplaySettings = create<DisplaySettingsState>((set, get) => {
  const initial = loadDisplaySettings()
  // Apply on startup
  if (typeof document !== 'undefined') applyCssVars(initial)

  return {
    settings: initial,
    update: (patch) => {
      const next = { ...get().settings, ...patch }
      set({ settings: next })
      saveDisplaySettings(next)
    },
  }
})
