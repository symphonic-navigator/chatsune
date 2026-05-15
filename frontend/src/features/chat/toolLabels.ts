export const TOOL_LABELS: Record<string, (args: Record<string, unknown>) => string> = {
  web_search: (args) => `Searching the web for "${args.query ?? '...'}"`,
  web_fetch: (args) => {
    const url = String(args.url ?? '')
    const display = url.length > 40 ? url.slice(0, 40) + '...' : url
    return `Fetching ${display}`
  },
  knowledge_search: (args) => `Searching knowledge for "${args.query ?? '...'}"`,
  create_artefact: (args) => `Creating artefact "${args.title ?? args.handle ?? '...'}"`,
  update_artefact: (args) => `Updating artefact "${args.handle ?? '...'}"`,
  read_artefact: (args) => `Reading artefact "${args.handle ?? '...'}"`,
  list_artefacts: () => 'Listing artefacts',
}

export function friendlyLabel(
  toolName: string,
  args: Record<string, unknown>,
): string {
  const fn = TOOL_LABELS[toolName]
  return fn ? fn(args) : `Running ${toolName}...`
}

export function displayName(toolName: string): string {
  // Strip namespace prefix if present (e.g. "global__quotes_about" -> "quotes_about").
  const parts = toolName.split('__')
  return parts.length > 1 ? parts.slice(1).join('__') : toolName
}
