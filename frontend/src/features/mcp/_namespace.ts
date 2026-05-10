/** Slugify a gateway display name into a stable namespace.
 * Mirrors backend `normalise_namespace` so frontend and backend agree on
 * which namespace each local gateway will live under. */
export function namespaceFromName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
}
