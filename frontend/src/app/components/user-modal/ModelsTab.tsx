import { ModelBrowser } from '../model-browser/ModelBrowser'

/**
 * User-facing models hub. Lists every model on every connection the
 * user owns, grouped by Connection, with per-model favourite / hidden /
 * customisation controls. The hub deliberately does not mutate persona
 * selections — those go through the ModelSelectionModal on EditTab.
 */
export function ModelsTab() {
  return <ModelBrowser />
}
