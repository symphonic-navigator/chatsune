/**
 * Pure decision function for how to handle an STT result returned during a
 * Tentative Barge. Kept free of React / audio dependencies so it can be
 * unit-tested without stubs.
 *
 *   stale   — a newer barge was started while STT was running; drop the
 *             result and do nothing.
 *   resume  — STT returned no text for the current barge; unmute and carry
 *             on with the assistant's reply.
 *   confirm — STT returned text for the current barge; this is a real
 *             barge. Cancel the assistant's reply and send the utterance.
 */
export type SttOutcome = 'stale' | 'resume' | 'confirm'

export interface SttDecisionInput {
  transcript: string
  sttBargeId: number
  currentBargeId: number
}

export function decideSttOutcome({ transcript, sttBargeId, currentBargeId }: SttDecisionInput): SttOutcome {
  if (sttBargeId !== currentBargeId) return 'stale'
  if (transcript.trim().length === 0) return 'resume'
  return 'confirm'
}
