/**
 * Voice-command type contracts.
 *
 * The foundation supports continuous-voice-only commands that bypass the LLM
 * entirely. Handlers receive the normalised body (everything after the
 * trigger word) and return a structured response that the response channel
 * renders as a toast plus, optionally, a tone cue.
 */

export type CueKind = 'on' | 'off' | 'error'

export interface CommandSpec {
  /** Single token: lowercase, no whitespace, no punctuation. e.g. 'debug', 'companion', 'hue'. */
  trigger: string

  /**
   * Default for what to do with the active response Group when this command
   * fires.
   * - 'abandon': cancel the paused Group entirely (e.g. `companion off`).
   * - 'resume': let the persona keep talking (e.g. `hue lights on`).
   *
   * Required on every handler — explicit intent over implicit default.
   * Handlers that need per-execution dynamism (e.g. `companion status` must
   * not abandon, but `companion off` must) can override per-call via
   * `CommandResponse.onTriggerWhilePlaying`.
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
  /** Optional tone cue to play through the dedicated cue audio channel. */
  cue?: CueKind
  /** Toast message. Always rendered, regardless of cue. */
  displayText: string
  /**
   * Per-execution override of `CommandSpec.onTriggerWhilePlaying`. When set,
   * takes precedence over the static default registered with the spec.
   * Use case: a single trigger that branches behaviour by body content
   * (e.g. `companion off` must abandon, `companion status` must not).
   */
  onTriggerWhilePlaying?: 'abandon' | 'resume'
}

export type DispatchResult =
  | { dispatched: false }
  | { dispatched: true; onTriggerWhilePlaying: 'abandon' | 'resume' }
