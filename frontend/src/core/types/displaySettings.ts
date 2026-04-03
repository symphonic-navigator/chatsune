// frontend/src/core/types/displaySettings.ts

export interface DisplaySettings {
  chatFontFamily: 'serif' | 'sans-serif'
  chatFontSize: 'normal' | 'large' | 'very-large'
  chatLineHeight: 'small' | 'normal' | 'large' | 'very-large'
  uiScale: 100 | 110 | 120 | 130
  whiteScript: boolean
}

export const DEFAULT_DISPLAY_SETTINGS: DisplaySettings = {
  chatFontFamily: 'serif',
  chatFontSize: 'normal',
  chatLineHeight: 'normal',
  uiScale: 100,
  whiteScript: false,
}

export const FONT_FAMILY_VALUES: Record<DisplaySettings['chatFontFamily'], string> = {
  serif: "'Lora', Georgia, serif",
  'sans-serif': "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
}

export const FONT_SIZE_VALUES: Record<DisplaySettings['chatFontSize'], string> = {
  normal: '14px',
  large: '16px',
  'very-large': '19px',
}

export const LINE_HEIGHT_VALUES: Record<DisplaySettings['chatLineHeight'], string> = {
  small: '1.5',
  normal: '1.65',
  large: '1.9',
  'very-large': '2.1',
}

export const UI_SCALE_OPTIONS: Array<DisplaySettings['uiScale']> = [100, 110, 120, 130]
