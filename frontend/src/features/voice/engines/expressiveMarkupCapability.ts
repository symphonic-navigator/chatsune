// Capability string as declared in shared/dtos/integrations.py:
// IntegrationCapability.TTS_EXPRESSIVE_MARKUP.
const CAPABILITY = 'tts_expressive_markup'

export function providerSupportsExpressiveMarkup(
  integrationId: string | null | undefined,
  definitions: ReadonlyArray<{ id: string; capabilities?: readonly string[] }>,
): boolean {
  if (!integrationId) return false
  const defn = definitions.find((d) => d.id === integrationId)
  if (!defn) return false
  return (defn.capabilities ?? []).includes(CAPABILITY)
}
