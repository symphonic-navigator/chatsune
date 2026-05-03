/**
 * Frontend feature gates.
 *
 * Single boolean constants flipped manually when a backend feature is
 * ready to render. Intentionally simple — no env wiring, no runtime
 * fetch — because the gates are reviewed and committed alongside the
 * code that consumes them.
 */

export const PROJECTS_ENABLED = false
