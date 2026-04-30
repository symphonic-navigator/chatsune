interface Props {
  pillContent: string
}

/**
 * Inline pill rendered in chat for an integration's stream tag.
 *
 * Used by all integrations (Lovense, future Screen Effects, ...) for visual
 * consistency with xAI voice-expression tag pills. The shared `.voice-tag,
 * .integration-pill` rule in `src/index.css` keeps the two pill aesthetics
 * identical without duplicating styling.
 */
export function IntegrationPill({ pillContent }: Props) {
  return <span className="integration-pill">{pillContent}</span>
}
