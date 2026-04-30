/**
 * Voice-command type contracts.
 *
 * The foundation supports continuous-voice-only commands that bypass the LLM
 * entirely. Handlers receive the normalised body (everything after the
 * trigger word) and return a structured response that the response channel
 * renders — today as a toast, in part 2 as a cached system-voice utterance
 * with toast fallback.
 */

export interface CommandSpec {
  /** Single token: lowercase, no whitespace, no punctuation. e.g. 'debug', 'companion', 'hue'. */
  trigger: string

  /**
   * What to do with the active response Group when this command fires.
   * - 'abandon': cancel the paused Group entirely (e.g. 'companion off').
   * - 'resume': let the persona keep talking (e.g. 'hue lights on').
   * Required on every handler — explicit intent over implicit default.
   */
  onTriggerWhilePlaying: 'abandon' | 'resume'

  /** Source label for logs / debug. 'core' for built-ins, `integration:${id}` for plugins. */
  source: string

  /**
   * Execute the command. `body` is the normalised remainder after the trigger word
   * (may be ''). Async because handlers may do API calls. Throws are caught by the
   * dispatcher and converted to error responses.
   */
  execute: (body: string) => Promise<CommandResponse>
}

export interface CommandResponse {
  level: 'success' | 'info' | 'error'
  /** What the system-voice will say in part 2. v1 logs only, does not render. */
  spokenText: string
  /** What the toast displays in v1; persists as fallback in part 2. */
  displayText: string
}

export type DispatchResult =
  | { dispatched: false }
  | { dispatched: true; onTriggerWhilePlaying: 'abandon' | 'resume' }
