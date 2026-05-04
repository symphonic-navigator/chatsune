import type { CSSProperties } from 'react'

/**
 * Inline style for "secret-like" inputs (API keys, tokens) that we want
 * masked visually but **not** treated as a password by the browser —
 * `type="password"` triggers the password-manager prompt, which is
 * unwanted for API-key entry.
 *
 * `-webkit-text-security: disc` is supported in Chrome, Safari, and
 * Firefox 111+ (March 2023 onwards). For very old Firefox the value
 * would render in plain text — accepted risk.
 */
export const SECRET_INPUT_STYLE: CSSProperties = {
  WebkitTextSecurity: 'disc',
} as CSSProperties

/** Spread on a secret-like input to disable browser + password-manager autofill. */
export const SECRET_INPUT_NO_AUTOFILL = {
  autoComplete: 'off',
  spellCheck: false,
  'data-1p-ignore': true,
  'data-lpignore': 'true',
  'data-bwignore': 'true',
} as const
